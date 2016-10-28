#pragma once

#include <stdint.h>

// Buffer sizes, must be powers of 2.
#ifndef BUFFY_TX_BUF_SIZE
#define BUFFY_TX_BUF_SIZE 512
#endif

#ifndef BUFFY_RX_BUF_SIZE
#define BUFFY_RX_BUF_SIZE 64
#endif

#define BUFFY_MAGIC 0xdd664662  // bFfY'

struct buffy {
  const uint32_t magic;
  // TX buffer size as log2 of the size.
  const uint32_t tx_len_pow2;
  // RX buffer size as log2 of the size.
  const uint32_t rx_len_pow2;
  // Head/tail location as index into the buffers.
  volatile uint32_t tx_tail;
  volatile uint32_t tx_head;
  volatile uint32_t rx_tail;
  volatile uint32_t rx_head;
  // Buffers themselves.
  uint8_t tx_buf[BUFFY_TX_BUF_SIZE];
  uint8_t rx_buf[BUFFY_RX_BUF_SIZE];
};

// Copies data to be sent to the transmit buffer.
//
// Returns number of characters queued. This number might be smaller
// than requested number if there is no space in the buffer.
int buffy_tx(struct buffy* t, const char* buf, int len);

// Attempts to read from the receive buffer for up to len characters.
//
// Returns the number of characters received.
int buffy_rx(struct buffy* t, char* buf, int len);

#define INSTANTIATE_BUFFY(name)                                 \
  static struct buffy name = {                                  \
      .magic = BUFFY_MAGIC,                                     \
      .tx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_TX_BUF_SIZE), \
      .rx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_RX_BUF_SIZE), \
      .tx_tail = 0,                                             \
      .tx_head = 0,                                             \
      .rx_tail = 0,                                             \
      .rx_head = 0,                                             \
  };
