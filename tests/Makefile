DEFINES += -DBUFFY_TX_BUF_SIZE=16
DEFINES += -DBUFFY_RX_BUF_SIZE=8
DEFINES += -DTESTING=1
CFLAGS := -Wall -Werror
SRC_DIR := ../embedded
INCLUDES := -I$(SRC_DIR) -I../external/cutest/include

all: buffy_test_run
.PHONY: all

buffy_test_run: buffy_test
	./buffy_test

buffy_test: buffy_test.c $(SRC_DIR)/buffy.c $(SRC_DIR)/buffy.h ../external/cutest/include/cutest.h
	gcc $(CFLAGS) $(DEFINES) $(INCLUDES) $< $(SRC_DIR)/buffy.c -o $@

# Pull in external submodules if they are not present.
../external/cutest/include/cutest.h:
	git submodule init
	git submodule update
