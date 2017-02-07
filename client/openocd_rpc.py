#!/usr/bin/env python3
#
# Interface to talk to openocd's RPC server.
#
# See: http://openocd.org/doc/html/Tcl-Scripting-API.html

import socket
import threading
import time
import traceback

# Input and output terminator.
CMD_TERMINATOR = b'\x1a'
# Default TCP port OpenOCD listens on.
DEFAULT_PORT = 6666
# Seconds to wait for a response.
TIMEOUT = 2


class OpenOcdError(Exception):
    pass


class OpenOcdRpc:
    def __init__(self,
                 port=DEFAULT_PORT,
                 prepare_commands=None,
                 tries=1,
                 verbose=False):
        """Initializes openocd interface.

        Args:
          port: int, TCP port to connect to.
          prepare_commands: list of str, if specified, gets executed
              before we start sending commands (or after an error).
          tries: int, number of tries to do before giving up.
          verbose: bool, whether to output debug info.
        """
        self._prepare_commands = prepare_commands or []
        self._tries = tries
        self._wait_between_tries = 1  # seconds
        # Whether we have sent the prepare commands.
        self._prepared = False
        self._verbose = verbose

        self._sock = socket.create_connection(('localhost', port), TIMEOUT)
        self._remaining_buffer_bytes = None
        self._lock = threading.Lock()

    def _maybe_retry(self, cmd, *args, **kwargs):
        """If self._tries > 1, handles BuffyError retries."""
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

    def send_command(self, cmd):
        """Sends given command, returns the response as bytes."""
        with self._lock:
            return self._send_command_locked(cmd)

    def _send_command_locked(self, cmd):
        if not self._prepared:
            for command in self._prepare_commands:
                self._send_command_locked_real(command)
        self._prepared = True
        return self._send_command_locked_real(cmd)

    def _send_command_locked_real(self, cmd):
        if self._verbose:
            print('>%s' % cmd)
        cmd = cmd.encode('utf-8') + CMD_TERMINATOR
        self._sock.send(cmd)
        received = []
        while True:
            if self._remaining_buffer_bytes:
                # We had data left over from previous read. Process that first.
                tmp = self._remaining_buffer_bytes
                self._remaining_buffer_bytes = None
            else:
                tmp = self._sock.recv(1024)
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

    def _read_word_locked(self, address):
        """Reads a 32-bit word from given address."""
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
            return self._maybe_retry(self._read_memory_locked, *args, **kwargs)

    def _read_memory_locked(self, address, count, width=32):
        """Reads count elements with given width starting from address.

        Returns:
            list of ints, whose width depends on the 'width' argument
        """
        # Unset array first, otherwise, if count is smaller, it will return previous values.
        self._send_command_locked('array unset _rpc_array')
        self._send_command_locked('mem2array _rpc_array %d 0x%x %d' %
                                  (width, address, count))
        mem_bytes_hex = self._send_command_locked('ocd_echo $_rpc_array')
        # The return value is pairs of <array index> <value>. The array indices
        # are not neccessarily in order. (Yay TCL!)
        items = mem_bytes_hex.split(b' ')
        if len(items) % 2:
            raise OpenOcdError('Got unexpected response from mem2array: "%s"' %
                               mem_bytes_hex)
        # Parse as integers and sort in proper order.
        items = [int(x, 10) for x in items]
        pairs = sorted(zip(items[::2], items[1::2]))
        # Now that they are sorted, return an array of second elements (values).
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
        array = ' '.join(['%d 0x%x' % (index, value)
                          for index, value in enumerate(values)])
        count = len(values)
        self._send_command_locked('array unset _rpc_array')
        self._send_command_locked('array set _rpc_array { %s }' % array)
        self._send_command_locked('array2mem _rpc_array %d 0x%x %d' %
                                  (width, address, count))
