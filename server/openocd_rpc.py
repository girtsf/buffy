#!/usr/bin/env python3
#
# Interface to talk to openocd's RPC server.
#
# See: http://openocd.org/doc/html/Tcl-Scripting-API.html

import socket

# Input and output terminator.
CMD_TERMINATOR = b'\x1a'
# Default TCP port OpenOCD listens on.
DEFAULT_PORT = 6666


class OpenOcdError(Exception):
    pass


class OpenOcdRpc:
    def __init__(self, port=DEFAULT_PORT):
        self._sock = socket.create_connection(('localhost', port))
        self._remaining_buffer_bytes = None

    def send_command(self, cmd):
        """Sends given command, returns the response as bytes."""
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
        """Reads a 32-bit word from given address."""
        out = self.send_command('ocd_mdw 0x%x' % address)
        # Return format:
        # 0x20002000: 00000000
        if out.count(b':') != 1:
            raise OpenOcdError('Failed to read memory at 0x%x. Got: "%s"' %
                               (address, out))
        address_out, value = out.split(b':')
        if int(address_out, 0) != address:
            raise OpenOcdError('Unexpected address: %s' % addreses_out)
        return int(value, 16)

    def write_word(self, address, value):
        """Writes a 32-bit value to a given address."""
        self.send_command('ocd_mww 0x%x 0x%x' % (address, value))

    def read_memory(self, address, count, width=32):
        """Reads count elements with given width starting from address."""
        # Unset array first, otherwise, if count is smaller, it will return previous values.
        self.send_command('array unset output')
        self.send_command('mem2array output %d 0x%x %d' %
                          (width, address, count))
        mem_bytes_hex = self.send_command('ocd_echo $output')
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
