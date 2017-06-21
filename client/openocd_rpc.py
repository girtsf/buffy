#!/usr/bin/env python3
#
# Interface to talk to openocd's RPC server.
#
# See: http://openocd.org/doc/html/Tcl-Scripting-API.html

import re
import socket
import threading
import time
import traceback

# Input and output terminator.
CMD_TERMINATOR = b'\x1a'
# Default TCP port OpenOCD listens on.
DEFAULT_PORT = 6666
# Number of words to read at a time for read_memory.
READ_CHUNK_SIZE = 4096


class OpenOcdError(Exception):
    pass


class OpenOcdRpc:
    def __init__(self,
                 port=DEFAULT_PORT,
                 prepare_commands=None,
                 tries=1,
                 verbose=False,
                 timeout=2,
                 array_var_name='_rpc_array',
                 ignore_regexps=[]):
        """Initializes openocd interface.

        Args:
          port: int, TCP port to connect to.
          prepare_commands: list of str, if specified, gets executed
              before we start sending commands (or after an error).
          tries: int, number of tries to do before giving up.
          verbose: bool, whether to output debug info.
          timeout: int, default time in seconds to wait for a response on RPC
              port.
          array_var_name: str, TCL variable name to use for storing
              intermediate data when reading or writing chunks of memory. If
              you intend to use multiple OpenOcdRpc instances against a single
              openocd process concurrently, you might want to use different var
              names.
          ignore_regexps: list of str, regular expressions that indicate a
              line from OpenOCD should be ignored when reading output.
        """
        self._prepare_commands = prepare_commands or []
        self._tries = tries
        self._wait_between_tries = 1  # seconds
        # Whether we have sent the prepare commands.
        self._prepared = False
        self._verbose = verbose
        self._timeout = timeout
        self._array_var_name = array_var_name
        self._ignore_regexps = ignore_regexps

        self._sock = socket.create_connection(('localhost', port),
                                              self._timeout)
        self._remaining_buffer_bytes = None
        self._lock = threading.Lock()

    def _flush_socket(self):
        """Keeps reading from socket until nothing comes out."""
        # Use a shorter timeout instead of default.
        self._sock.settimeout(0.05)
        while True:
            try:
                flushed = self._sock.recv(1024)
            except socket.timeout:
                break
            if not flushed:
                break
            print('Flushed %d bytes' % len(flushed))

    def _maybe_retry(self, cmd, *args, **kwargs):
        """If self._tries > 1, handles retries. Called under lock."""
        tries_left = self._tries
        while tries_left:
            try:
                return cmd(*args, **kwargs)
            except OpenOcdError as e:
                self._prepared = False
                tries_left -= 1
                if not tries_left:
                    raise
                traceback.print_exc()
                print('Waiting for %d s before retrying %d more time(s)' %
                      (self._wait_between_tries, tries_left))
                time.sleep(self._wait_between_tries)
                self._flush_socket()

    def send_command(self, cmd, timeout=None):
        """Sends given command, returns the response as bytes."""
        with self._lock:
            return self._send_command_locked(cmd, timeout=timeout)

    def _send_command_locked(self, cmd, timeout=None):
        if not self._prepared:
            for command in self._prepare_commands:
                self._send_command_locked_real(command, timeout=timeout)
        self._prepared = True
        return self._send_command_locked_real(cmd, timeout=timeout)

    def _send_command_locked_real(self, cmd, timeout=None):
        if self._verbose:
            print('>%s' % cmd)
        if timeout is not None:
            self._sock.settimeout(timeout)
        else:
            # Use default timeout.
            self._sock.settimeout(self._timeout)
        cmd = cmd.encode('utf-8') + CMD_TERMINATOR
        self._sock.send(cmd)
        received = []
        while True:
            if self._remaining_buffer_bytes:
                # We had data left over from previous read. Process that first.
                tmp = self._remaining_buffer_bytes
                self._remaining_buffer_bytes = None
            else:
                try:
                    tmp = self._sock.recv(1024)
                except socket.timeout:
                    raise OpenOcdError('Socket read timeout')

                if not tmp:
                    raise OpenOcdError('Socket read failed')
            if CMD_TERMINATOR in tmp:
                # We have a response.
                cmd_part, rest = tmp.split(CMD_TERMINATOR, 1)
                # Save remaining part (if any).
                self._remaining_buffer_bytes = rest
                received.append(cmd_part)
                break
            else:
                received.append(tmp)
        out = b''.join(received)
        return out

    def read_word(self, address):
        with self._lock:
            return self._maybe_retry(self._read_word_locked, address)

    def _should_ignore(self, line):
        line = line.decode('utf-8')
        for regexp in self._ignore_regexps:
            if re.match(regexp, line):
                return True
        return False

    def _read_word_locked(self, address):
        """Reads a 32-bit word from given address."""
        out = self._send_command_locked('ocd_mdw 0x%x' % address)
        while self._should_ignore(out):
            out = self._send_command_locked('ocd_mdw 0x%x' % address)

        # Return format:
        # 0x20002000: 00000000
        if out.count(b':') != 1:
            raise OpenOcdError('Failed to read memory at 0x%x. Got: "%s"' %
                               (address, out))
        address_out, value = out.split(b':')
        if int(address_out, 0) != address:
            raise OpenOcdError('Unexpected address: %s, wanted: 0x%x' %
                               (address_out, address))
        return int(value, 16)

    def write_word(self, address, value):
        with self._lock:
            return self._maybe_retry(self._write_word_locked, address, value)

    def _write_word_locked(self, address, value):
        """Writes a 32-bit value to a given address."""
        self._send_command_locked('ocd_mww 0x%x 0x%x' % (address, value))

    def read_memory(self, *args, **kwargs):
        with self._lock:
            return self._read_memory_locked(*args, **kwargs)

    def _read_memory_locked(self, address, count, width=32):
        """Reads count elements with given width starting from address.

        Returns:
            list of ints, whose width depends on the 'width' argument
        """
        assert (width % 8) == 0
        out = []
        left = count
        while left > 0:
            this_count = min(left, READ_CHUNK_SIZE)
            out.extend(
                self._maybe_retry(
                    self._read_memory_chunk_locked,
                    address,
                    this_count,
                    width=width))
            # Count is in words.
            left -= this_count
            # Address is in bytes.
            address += this_count * (width // 8)
        return out

    def _read_memory_chunk_locked(self, address, count, width=32):
        """Reads one chunk (up to 32K) of values."""
        # Unset array first, otherwise, if count is smaller, it will return
        # previous values.
        self._send_command_locked('array unset %s' % self._array_var_name)
        self._send_command_locked('mem2array %s %d 0x%x %d' %
                                  (self._array_var_name, width, address,
                                   count))
        mem_bytes_hex = self._send_command_locked(
            'ocd_echo $%s' % self._array_var_name)
        # The return value is pairs of <array index> <value>. The array indices
        # are not neccessarily in order. (Yay TCL!)
        items = mem_bytes_hex.split(b' ')
        if len(items) % 2:
            raise OpenOcdError(
                'Got unexpected response from mem2array: "%s"' % mem_bytes_hex)
        # Parse as integers and sort in proper order.
        try:
            items = [int(x, 10) for x in items]
        except ValueError as e:
            raise OpenOcdError('Failed decoding memory: %s' % e)
        pairs = sorted(zip(items[::2], items[1::2]))
        # Now that they are sorted, return an array of second elements
        # (values).
        return [y for x, y in pairs]

    def write_memory(self, *args, **kwargs):
        with self._lock:
            return self._maybe_retry(self._write_memory_locked, *args,
                                     **kwargs)

    def _write_memory_locked(self, address, values, width=32):
        """Writes to memory.

        Args:
            address: int, address to write to
            values: list of ints
            width: int, write width in bits
        """
        if not values:
            raise OpenOcdError('Empty array passed to write_memory!')
        array = ' '.join(
            ['%d 0x%x' % (index, value) for index, value in enumerate(values)])
        count = len(values)
        self._send_command_locked('array unset %s' % self._array_var_name)
        self._send_command_locked('array set %s { %s }' %
                                  (self._array_var_name, array))
        self._send_command_locked('array2mem %s %d 0x%x %d' %
                                  (self._array_var_name, width, address,
                                   count))
