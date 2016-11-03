DEFINES += -DBUFFY_TX_BUF_SIZE=16
DEFINES += -DBUFFY_RX_BUF_SIZE=8
DEFINES += -DTESTING=1
CFLAGS := -Wall -Werror
INCLUDES := -Iinclude -Iexternal/cutest/include

all: buffy_test_run
.PHONY: all

buffy_test_run: buffy_test
	./buffy_test

buffy_test: buffy_test.c buffy.c include/lib/buffy.h external/cutest/README.md
	gcc $(CFLAGS) $(DEFINES) $(INCLUDES) $< buffy.c -o $@

# Pull in external submodules if they are not present.
external/cutest/README.md:
	git submodule init
	git submodule update
