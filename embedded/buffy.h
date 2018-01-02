#pragma once

#include <stdint.h>

// Buffer sizes, must be powers of 2.
#ifndef BUFFY_TX_BUF_SIZE
#define BUFFY_TX_BUF_SIZE 512
#endif

#ifndef BUFFY_RX_BUF_SIZE
#define BUFFY_RX_BUF_SIZE 64
#endif

// First version of buffy used 0xdd664662.
//
// The new version now also includes a version field in the structure.
#define BUFFY_MAGIC 0xdd664642  // BFfY'

struct buffy {
  const uint32_t magic;       // 0
  const uint8_t version;      // 4
  const uint8_t tx_len_pow2;  // 5 - TX buffer size as log2 of the size.
  const uint8_t rx_len_pow2;  // 6 - RX buffer size as log2 of the size.
  const uint8_t initialized;  // 7
  volatile uint32_t tx_tail;  // 8 - heads/tails as indexes.
  volatile uint32_t tx_head;  // 12
  volatile uint32_t rx_tail;  // 16
  volatile uint32_t rx_head;  // 20
  volatile uint32_t tx_overflow_counter;  // 24
  uint8_t* tx_buf;                        // 28 - pointer to tx buffer.
  uint8_t* rx_buf;                        // 32 - pointer to rx buffer.
};

// Transmit buffer: from embedded to host.
// =======================================
// Copies data to be sent to the transmit buffer.
//
// Returns number of characters queued. This number might be smaller
// than requested number if there is no space in the buffer.
int buffy_tx(struct buffy* t, const char* buf, int len);

// Attempts to read from the *transmit* buffer (characters that are pending
// host's) read. You would typically not want to use this. Also, there is
// no synchronization between this and the reader on the host. So if there is
// a host reader and it updates the pointers through the debug interface,
// interesting things might happen.
//
// Returns number of characters written to 'buf' (up to 'len').
int buffy_tx_buffer_read(struct buffy* t, char* buf, int len);

// Returns the usable size of the TX buffer in bytes.
//
// This includes bytes that have not yet been read out). Due to circular buffer
// implementation reasons the usable buffer size is one smaller than the actual
// buffer. This is accounted for in the return value of this function.
int buffy_tx_get_buffer_size(struct buffy* t);

// Returns number of bytes free in the TX buffer.
int buffy_tx_get_buffer_free(struct buffy* t);

// Receive buffer: from host to embedded.
// ======================================
// Attempts to read from the receive buffer for up to len characters.
//
// Returns the number of characters received.
int buffy_rx(struct buffy* t, char* buf, int len);

// Macro to instantiate a buffy structure + rx and tx buffers.
#define INSTANTIATE_BUFFY(name)                                 \
  static uint8_t name##_tx_buf[BUFFY_TX_BUF_SIZE];              \
  static uint8_t name##_rx_buf[BUFFY_RX_BUF_SIZE];              \
  static struct buffy name = {                                  \
      .magic = BUFFY_MAGIC,                                     \
      .version = 1,                                             \
      .tx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_TX_BUF_SIZE), \
      .rx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_RX_BUF_SIZE), \
      .tx_tail = 0,                                             \
      .tx_head = 0,                                             \
      .rx_tail = 0,                                             \
      .rx_head = 0,                                             \
      .tx_overflow_counter = 0,                                 \
      .version = 1,                                             \
      .tx_buf = name##_tx_buf,                                  \
      .rx_buf = name##_rx_buf,                                  \
  };

// Macro to instantiate structure and buffers, placing the structure in
// a particular linker section.
//
// This might be useful to place the buffy struct before other .data. That way,
// it will always end up at same address, making it easier to find.
#define INSTANTIATE_BUFFY_IN_SECTION(name, linker_section)              \
  static uint8_t name##_tx_buf[BUFFY_TX_BUF_SIZE];                      \
  static uint8_t name##_rx_buf[BUFFY_RX_BUF_SIZE];                      \
  __attribute__((section(linker_section))) static struct buffy name = { \
      .magic = BUFFY_MAGIC,                                             \
      .version = 1,                                                     \
      .tx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_TX_BUF_SIZE),         \
      .rx_len_pow2 = 32 - 1 - __builtin_clz(BUFFY_RX_BUF_SIZE),         \
      .tx_tail = 0,                                                     \
      .tx_head = 0,                                                     \
      .rx_tail = 0,                                                     \
      .rx_head = 0,                                                     \
      .tx_overflow_counter = 0,                                         \
      .tx_buf = name##_tx_buf,                                          \
      .rx_buf = name##_rx_buf,                                          \
  };
