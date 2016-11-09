#!/usr/bin/env python3
#
# Interface to buffy terminal through OpenOCD's RPC server.

import sys
import threading
import time

import console
import openocd_rpc


BUFFY_MAGIC = 0xdd664662

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
                 verbose=False):
        self._alive = False
        self._console_reader_thread = None
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

    def _find_magic(self, ram_start, ram_size):
        """Looks for BUFFY_MAGIC in ram, returns first address."""
        for i in range(0, ram_size, 4):
            v = self._rpc.read_word(ram_start + i)
            if v == BUFFY_MAGIC:
                if self._verbose:
                    print('Found magic at 0x%x' % i)
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
        # TODO: synchronize openocd access.
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
            self._rpc.write_memory(rx_buf_address + head, buf_to_write, width=8)

            new_rx_head = (head + write_len) % self._rx_buf_size
            self._set_rx_head(new_rx_head)

            buf = buf[write_len:]

    def start(self):
        self._alive = True
        self._console.setup()
        self._start_console_reader()

    def join(self):
        self.watch()
        self._console_reader_thread.join()

    def _start_console_reader(self):
        self._console_reader_thread = threading.Thread(target=self._console_reader, name='console_reader')
        self._console_reader_thread.daemon = True
        self._console_reader_thread.start()

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

            time.sleep(0.2)


if __name__ == '__main__':
    rpc = openocd_rpc.OpenOcdRpc()
    # TODO: command line flags + rc.
    ram_start = 0x10000000
    ram_size = 0x2000
    buffy = Buffy(rpc, ram_start=ram_start, ram_size=ram_size, verbose=False)
    buffy.start()
    buffy.join()
