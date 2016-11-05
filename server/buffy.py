#!/usr/bin/env python3
#
# Interface to buffy terminal through OpenOCD's RPC server.

import sys
import time

import openocd_rpc


BUFFY_MAGIC = 0xdd664662
TX_TAIL_OFFSET = 12
TX_HEAD_OFFSET = 16
TX_BUF_OFFSET = 28


class BuffyError(Exception):
    pass


class Buffy:
    def __init__(self,
                 rpc,
                 ram_start=None,
                 ram_size=None,
                 buffy_address=None,
                 verbose=False):
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

    def watch(self):
        while True:
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

            time.sleep(1)


if __name__ == '__main__':
    rpc = openocd_rpc.OpenOcdRpc()
    # TODO: command line flags + rc.
    ram_start = 0x10000000
    ram_size = 0x2000
    buffy = Buffy(rpc, ram_start=ram_start, ram_size=ram_size, verbose=False)
    buffy.watch()
