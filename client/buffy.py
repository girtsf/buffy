#!/usr/bin/env python3
#
# Interface to buffy debug console through OpenOCD's RPC server.

import argparse
import configparser
import sys
import threading
import time
import os

# Local imports.
import console
import openocd_rpc

# Path to store previous locations of buffy datastructure addresses, keyed
# by target name (if provided). If file does not exist or target is not found
# in the file, buffy will scan for the datastructure in memory and write it
# out to the file.
BUFFY_PREVIOUS_ADDRESS_FILE = os.path.expanduser('~/.buffy_previous_address')

# If not specified, where to start scanning through RAM to look for buffy
# structure.
DEFAULT_RAM_START = 0x10000000
# How far to keep looking.
DEFAULT_RAM_SIZE = 128 * 1024

# Magic value that marks the start of buffy structure.
BUFFY_MAGIC = 0xdd664662

# Offsets in bytes from the start of the magic value. Values here must match
# the structure defined in buffy.h.
TX_TAIL_OFFSET = 12
TX_HEAD_OFFSET = 16
RX_TAIL_OFFSET = 20
RX_HEAD_OFFSET = 24
TX_OVERFLOW_COUNTER = 28
TX_BUF_OFFSET = 32


class BuffyError(Exception):
    pass


class Buffy:
    def __init__(self,
                 rpc,
                 ram_start=None,
                 ram_size=None,
                 buffy_address=None,
                 target_name='default',
                 tcp_server_port=None,
                 verbose=False):
        """Initializes Buffy class.

        Args:
          rpc: OpenOcdRpc object.
          ram_start: int, optional, address where we start looking for buffy
              structure. Either ram_start+ram_size or buffy_address must be
              given.
          ram_size: int, optional, RAM size in bytes - how far do we keep
              looking before giving up.
          buffy_address: int, optional, address of the buffy buffer. Can be
              used instead of ram_start/ram_size if the location is known.
          target_name: str, name to use for storing/recalling previous address.
          tcp_server_port: int, optional. If given, starts up a TCP server
              that will send all data received on the TCP socket through
              buffy to target.
          verbose: bool, whether to be spammy.
        """
        self._alive = False
        self._console_reader_thread = None
        self._tcp_server_port = tcp_server_port
        self._tcp_server = None
        self._target_name = target_name
        self._console = console.Console()
        self._rpc = rpc
        self._verbose = verbose

        if (ram_start is None or ram_size is None) and (buffy_address is None):
            raise ValueError(
                'Either buffy_address or ram_start & ram_size must'
                ' be provided')

        if buffy_address:
            self._buffy_address = buffy_address
        else:
            self._buffy_address = self._find_magic(ram_start, ram_size)

        header = rpc.read_memory(self._buffy_address, 3)  # 3 words
        self._parse_header(header)

    @staticmethod
    def _read_previous_address(target_name):
        """Returns previous buffy address or None."""
        if not os.path.exists(BUFFY_PREVIOUS_ADDRESS_FILE):
            return None
        config = configparser.ConfigParser()
        config.read(BUFFY_PREVIOUS_ADDRESS_FILE)
        if target_name in config and 'address' in config[target_name]:
            return int(config[target_name]['address'], 0)

        return None

    @staticmethod
    def _write_previous_address(target_name, address):
        config = configparser.ConfigParser()
        if os.path.exists(BUFFY_PREVIOUS_ADDRESS_FILE):
            config.read(BUFFY_PREVIOUS_ADDRESS_FILE)
        if target_name not in config:
            config.add_section(target_name)
        config[target_name]['address'] = '0x%x' % address
        with open(BUFFY_PREVIOUS_ADDRESS_FILE, 'wt') as fh:
            config.write(fh)

    def _find_magic(self, ram_start, ram_size):
        """Looks for BUFFY_MAGIC in ram, returns first address."""
        previous_address = self._read_previous_address(self._target_name)
        if previous_address is not None:
            v = self._rpc.read_word(previous_address)
            if v == BUFFY_MAGIC:
                if self._verbose:
                    print('Found magic at previous location 0x%x' %
                          previous_address)
                return previous_address

        for i in range(0, ram_size, 4):
            v = self._rpc.read_word(ram_start + i)
            if v == BUFFY_MAGIC:
                if self._verbose:
                    print('Found magic at 0x%x' % i)
                self._write_previous_address(self._target_name, ram_start + i)
                return ram_start + i
        raise BuffyError('Could not find magic word')

    def _parse_header(self, header_words):
        """Parses header, sets buffer sizes."""
        magic, tx_len_pow2, rx_len_pow2 = header_words
        if magic != BUFFY_MAGIC:
            raise BuffyError('Invalid magic in header')
        # Sanity checks.
        if ((tx_len_pow2 > 16) or (rx_len_pow2 > 16) or (tx_len_pow2 < 0) or
            (rx_len_pow2 < 0)):
            raise BuffyError('Invalid buffer sizes (tx: %d bits rx: %d bits)' %
                             (tx_len_pow2, rx_len_pow2))
        self._tx_buf_size = 1 << tx_len_pow2
        self._rx_buf_size = 1 << rx_len_pow2
        if self._verbose:
            print('Parsed header: tx buf size: %d rx buf size: %d' %
                  (self._tx_buf_size, self._rx_buf_size))

    def _get_tx_tail(self):
        """Returns current tail value."""
        return self._rpc.read_word(self._buffy_address + TX_TAIL_OFFSET)

    def _set_tx_tail(self, value):
        """Sets tail value."""
        return self._rpc.write_word(self._buffy_address + TX_TAIL_OFFSET,
                                    value)

    def _get_tx_head(self):
        """Returns current head value."""
        return self._rpc.read_word(self._buffy_address + TX_HEAD_OFFSET)

    def _get_rx_tail(self):
        """Returns current rx tail value."""
        return self._rpc.read_word(self._buffy_address + RX_TAIL_OFFSET)

    def _set_rx_head(self, value):
        """Sets rx head value."""
        return self._rpc.write_word(self._buffy_address + RX_HEAD_OFFSET,
                                    value)

    def _get_rx_head(self):
        """Returns current rx head value."""
        return self._rpc.read_word(self._buffy_address + RX_HEAD_OFFSET)

    def _get_tx_overflow_counter(self):
        """Returns current tx overflow counter value."""
        return self._rpc.read_word(self._buffy_address + TX_OVERFLOW_COUNTER)

    def pchr(self, i):
        if i > 32 and i < 128:
            return chr(i)
        else:
            return '\\x%02x' % i

    def d(self, x):
        return self.pchr(x & 0xff) + self.pchr((x >> 8) & 0xff) + self.pchr((
            x >> 16) & 0xff) + self.pchr(x >> 24)

    def dump_tx_buffer(self):
        buf = self._rpc.read_memory(self._buffy_address + TX_BUF_OFFSET,
                                    self._tx_buf_size // 4)
        print('len: %d' % len(buf))
        for i in range(0, len(buf), 20):
            print(''.join([self.d(x) for x in buf[i:i + 20]]))

    def dump_tx_buffer2(self):
        s = ''
        for i in range(0, self._tx_buf_size, 4):
            word = self._rpc.read_word(self._buffy_address + TX_BUF_OFFSET + i)
            s += self.d(word)
        print(s)

    def buffy_write(self, buf):
        """Writes given byte(s) to buffy."""
        while buf:
            tail = self._get_rx_tail()
            head = self._get_rx_head()
            if self._verbose:
                print('RX tail: %d head: %d' % (tail, head))
            if head >= tail:
                # Write to the end of the buffer.
                write_len = self._rx_buf_size - head
                if tail == 0:
                    # Special case - don't write all the way to the end.
                    write_len -= 1
            else:
                write_len = tail - head - 1
            if write_len == 0:
                print('WARNING: RX buffer full')
                return
            write_len = min(write_len, len(buf))
            if self._verbose:
                print('Writing %d bytes' % write_len)
            buf_to_write = buf[:write_len]

            rx_buf_address = self._buffy_address + TX_BUF_OFFSET + self._tx_buf_size
            self._rpc.write_memory(
                rx_buf_address + head, buf_to_write, width=8)

            new_rx_head = (head + write_len) % self._rx_buf_size
            self._set_rx_head(new_rx_head)

            buf = buf[write_len:]

    def start(self):
        self._alive = True
        self._console.setup()
        self._start_console_reader()
        if self._tcp_server_port:
            # Only import tcp_server here as it's not Python2 compatible.
            import tcp_server
            self._tcp_server = tcp_server.SimpleTcpServer(
                self._tcp_server_port, self.buffy_write)

    def join(self):
        self.watch()
        self._console_reader_thread.join()

    def _start_console_reader(self):
        self._console_reader_thread = threading.Thread(
            target=self._console_reader_start, name='console_reader')
        self._console_reader_thread.daemon = True
        self._console_reader_thread.start()

    def _console_reader_start(self):
        try:
            self._console_reader()
        finally:
            # If reader thread stops or dies, make watcher also die.
            print('console reader thread exited')
            self._alive = False

    def _console_reader(self):
        """Reads input from console, sends to buffy.

        _console_reader runs in a separate thread, reading characters
        from console, sending them to buffy.

        Exits if self._alive goes False.
        """
        while self._alive:
            try:
                c = self._console.getkey()
            except KeyboardInterrupt:
                self._alive = False
                break
            if ord(c) == 3:
                # CTRL-C (end of text)
                print('CTRL-C')
                self._alive = False
                break
            # TODO: maybe split out buffy and buffy_term?
            self.buffy_write(c.encode('utf-8'))
            # echo
            self._console.write(c)

    def watch(self):
        prev_overflow_counter = self._get_tx_overflow_counter()

        while self._alive:
            tail = self._get_tx_tail()
            head = self._get_tx_head()
            if tail != head:
                if self._verbose:
                    print('head: %d tail: %d tx_buf_size: %d' %
                          (head, tail, self._tx_buf_size))
                if head > tail:
                    read_len = head - tail
                else:
                    read_len = self._tx_buf_size - tail
                buf = self._rpc.read_memory(
                    self._buffy_address + TX_BUF_OFFSET + tail,
                    read_len,
                    width=8)
                sys.stdout.buffer.write(bytes(buf))
                sys.stdout.buffer.flush()
                new_tail = (tail + len(buf)) % self._tx_buf_size
                self._set_tx_tail(new_tail)
                continue

            overflow_counter = self._get_tx_overflow_counter()
            overflow_delta = overflow_counter - prev_overflow_counter
            if overflow_delta:
                print('TX side overflowed %d times!' % overflow_delta)
                prev_overflow_counter = overflow_counter

            time.sleep(0.5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--port',
        type=int,
        default=openocd_rpc.DEFAULT_PORT,
        help='OpenOCD TCP RPC port')
    parser.add_argument(
        '--ram_start',
        type=lambda x: int(x, 0),
        default=DEFAULT_RAM_START,
        help='RAM starting address')
    parser.add_argument(
        '--ram_size',
        type=lambda x: int(x, 0),
        default=DEFAULT_RAM_SIZE,
        help='Size of RAM')
    parser.add_argument(
        '--prepare_command',
        action='append',
        help='Command(s) to execute in the beginning')
    parser.add_argument(
        '--tries', type=int, default=1, help='Number of retries on error')
    parser.add_argument(
        '--tcp_server_port',
        type=int,
        default=None,
        help=('TCP port to listen on, if specified. Data sent to this port'
              ' gets sent over the Buffy link.'))
    parser.add_argument(
        '--target_name',
        type=str,
        default='default',
        help='Target name to use in storing previous buffy address location')
    parser.add_argument(
        '--verbose',
        dest='verbose',
        action='store_true',
        help='Whether to print debug info')
    parser.set_defaults(verbose=False)
    args = parser.parse_args()

    rpc = openocd_rpc.OpenOcdRpc(
        port=args.port,
        prepare_commands=args.prepare_command,
        tries=args.tries,
        verbose=args.verbose)
    buffy = Buffy(
        rpc,
        ram_start=args.ram_start,
        ram_size=args.ram_size,
        tcp_server_port=args.tcp_server_port,
        target_name=args.target_name,
        verbose=args.verbose)
    buffy.start()
    buffy.join()
