#include <string.h>

#if TESTING
#include <stdio.h>
#define DEBUG_PRINTF(x...) printf(x)
#else  // DEBUG
#define DEBUG_PRINTF(x...)
#endif
#include "buffy.h"

// A bunch of stuff was cribbed and/or inspired by LK's cbuf.

static inline void memory_barrier(void) {
#if !TESTING
  // On ARMv6m/v7: waits until memory is written out before returning.
  __asm__ volatile("dsb" ::: "memory");
#else  // TESTING
// noop on host.
#endif
}

static inline int min(int x, int y) {
  return x < y ? x : y;
}

static inline uint32_t modpow2(uint32_t value, uint32_t p2) {
  return value & ((1UL << p2) - 1);
}

static inline uint32_t valpow2(uint32_t p2) {
  return 1LU << p2;
}

int buffy_tx(struct buffy* t, const char* buf, int len) {
  int pos = 0;
  DEBUG_PRINTF("tx: %d\n", len);
  uint32_t tx_bufsize = valpow2(t->tx_len_pow2);
  memory_barrier();
  while (pos < len) {
    // Make a local copy of tail and head, as the debug reader could modify
    // the tail and mess up our calculations.
    uint32_t tail = t->tx_tail;
    uint32_t head = t->tx_head;
    // Safety check - if the reader clobbers head or tail with wrong values,
    // reset it back to zeroes and fail this write.
    if ((tail >= tx_bufsize) || (head >= tx_bufsize)) {
      DEBUG_PRINTF("tail or head went out of bounds, resetting\n");
      t->tx_tail = 0;
      t->tx_head = 0;
      memory_barrier();
      return 0;
    }

    DEBUG_PRINTF("head: %d tail: %d pos: %d\n", head, tail, pos);

    int write_len;
    if (head >= tail) {
      if (tail == 0) {
        // Special case for when tail is at 0. We don't want to write all the
        // way to the end then.
        write_len = valpow2(t->tx_len_pow2) - head - 1;
      } else {
        write_len = valpow2(t->tx_len_pow2) - head;
      }
    } else {
      // Calculate size from the start of the buffer to tail.
      write_len = tail - head - 1;
    }
    if (write_len == 0) {
      // Full.
      t->tx_overflow_counter++;
      memory_barrier();
      break;
    }
    write_len = min(write_len, len - pos);
    DEBUG_PRINTF("write_len: %d tx_len_pow2: %d\n", write_len, t->tx_len_pow2);
    memcpy(t->tx_buf + head, buf + pos, write_len);

    memory_barrier();

    // Write back to head. The tail could have been modified by the debug
    // reader, but that's fine.
    t->tx_head = modpow2(head + write_len, t->tx_len_pow2);

    memory_barrier();

    pos += write_len;
  }

  return pos;
}

int buffy_tx_buffer_read(struct buffy* t, char* buf, int len) {
  int pos = 0;
  DEBUG_PRINTF("tx_read: %d\n", len);
  memory_barrier();
  while (pos < len) {
    uint32_t tail = t->tx_tail;
    uint32_t head = t->tx_head;

    DEBUG_PRINTF("head: %d tail: %d pos: %d\n", head, tail, pos);

    if (head == tail) return pos;

    int read_len;
    if (head > tail) {
      // No wrap-around.
      read_len = head - tail;
    } else {
      // Read to the end of the buffer.
      read_len = valpow2(t->tx_len_pow2) - tail;
    }
    read_len = min(read_len, len - pos);
    DEBUG_PRINTF("read_len: %d tx_len_pow2: %d\n", read_len, t->tx_len_pow2);
    memcpy(buf + pos, t->tx_buf + tail, read_len);

    memory_barrier();

    t->tx_tail = modpow2(tail + read_len, t->tx_len_pow2);

    memory_barrier();

    pos += read_len;
  }

  return pos;
}

int buffy_tx_get_buffer_size(struct buffy* t) {
  // We can't store full 2**x bytes as we couldn't distinguish from an empty
  // buffer then.
  return valpow2(t->tx_len_pow2) - 1;
}

int buffy_tx_get_buffer_free(struct buffy* t) {
  uint32_t tail = t->tx_tail;
  uint32_t head = t->tx_head;
  if (head >= tail) {
    if (tail == 0) {
      // Special case for when tail is at 0. We don't want to write all the
      // way to the end then.
      return valpow2(t->tx_len_pow2) - head - 1;
    } else {
      // From head -> end.
      int second_half = valpow2(t->tx_len_pow2) - head;
      // From start to tail - 1.
      int first_half = tail - 1;
      return second_half + first_half;
    }
  } else {
    return tail - head - 1;
  }
}

int buffy_rx(struct buffy* t, char* buf, int len) {
  int pos = 0;
  DEBUG_PRINTF("rx: %d\n", len);
  uint32_t rx_bufsize = valpow2(t->rx_len_pow2);
  memory_barrier();
  while (pos < len) {
    // Make a local copy of tail and head, as the debug writer could modify
    // the head and mess up our calculations.
    uint32_t tail = t->rx_tail;
    uint32_t head = t->rx_head;

    // Safety check - if the reader clobbers head or tail with wrong values,
    // reset it back to zeroes and fail this write.
    if ((tail >= rx_bufsize) || (head >= rx_bufsize)) {
      DEBUG_PRINTF("tail or head went out of bounds, resetting\n");
      t->rx_tail = 0;
      t->rx_head = 0;
      memory_barrier();
      return 0;
    }

    DEBUG_PRINTF("head: %d tail: %d pos: %d\n", head, tail, pos);

    if (head == tail) return pos;

    int read_len;
    if (head > tail) {
      // No wrap-around.
      read_len = head - tail;
    } else {
      // Read to the end of the buffer.
      read_len = valpow2(t->rx_len_pow2) - tail;
    }
    read_len = min(read_len, len - pos);
    DEBUG_PRINTF("read_len: %d rx_len_pow2: %d\n", read_len, t->rx_len_pow2);
    memcpy(buf + pos, t->rx_buf + tail, read_len);

    memory_barrier();

    // Write back to tail. The head could have been modified by the debug
    // writer, but that's fine.
    t->rx_tail = modpow2(tail + read_len, t->rx_len_pow2);

    memory_barrier();

    pos += read_len;
  }

  return pos;
}
