# Buffy

Buffy is a debugging buffer library for embedded targets.

Buffy creates a circular buffer on the target side. Your code writes debug logs
to this buffer, and it gets read from the PC side over a JTAG connection.

Buffy consists of two parts:
1. a small library that you link into your embedded code (this repo)
2. a python script that uses OpenOCD to exchange data with the code on the
   embedded side (see [buffy-client](https://github.com/astranis/buffy-client))

## Usage

You should be able to interact with the target using OpenOCD. It should have
`tcl_port` enabled (default).

On the embedded side add `embedded/buffy.c` and `embedded/buffy.h` to your
project using your favorite build system. Somewhere in your code include
`buffy.h` and instantiate the debug buffer with `INSTANTIATE_BUFFY(buffy);`.
Then_set up data to be sent to host with `buffy_tx(&buffy, buf, len)`. You
might want to create some sort of `printf` function that `sprintf`s into
a buffer before calling `buffy_tx`.

See the [buffy-client](https://github.com/astranis/buffy-client) repo for the
usage on the client side.

## More Details

When you instantiate Buffy on the target, it creates two circular buffers, one
for sending data from target to host, and one for reverse. The data structure
also contains a magic word that the client can use to find the structure in
memory.

Buffy uses OpenOCD's "RPC" interface to get data between the client and the
embedded target. It could use some improvements.

## Supported Devices

This has been tested on 3+ Cortex ARM devices from different vendors. It should
work on other platforms with minimal changes as long as your target has 32-bit
wide debug access, and allows OpenOCD to read/write memory while the target is
running.

## Contributing

Pull requests are welcome. Also, I would love if somebody cleaned up OpenOCDs
RPC interface so it was less spammy and more reliable.

## License

Stuff under `external/` has their own licenses, everything else is BSD. See
`LICENSE`.

## Acknowledgements

Inspired by nekromant's stlinky and lk's cbuf.
