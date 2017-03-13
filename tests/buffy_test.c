#include "buffy.h"

#include <stdio.h>
#include <string.h>  // memcmp

#include <cutest.h>

#define TEST_EQ(a, b)                          \
  do {                                         \
    typeof(a) _a = (a);                        \
    typeof(b) _b = (b);                        \
    TEST_CHECK_(_a == _b, "%d != %d", _a, _b); \
  } while (0)

void test_tx(void) {
  // Note, the define in Makefile sets TX buffer to 16B.
  INSTANTIATE_BUFFY(buffy);
  TEST_EQ(buffy.tx_head, 0);
  TEST_EQ(buffy.tx_tail, 0);
  TEST_EQ(buffy_tx_get_buffer_size(&buffy), 15);

  TEST_EQ(buffy_tx(&buffy, "wahhh", 5), 5);
  TEST_EQ(buffy.tx_head, 5);
  TEST_EQ(buffy.tx_tail, 0);

  TEST_EQ(buffy_tx(&buffy, "foo", 3), 3);
  TEST_EQ(buffy.tx_head, 8);
  TEST_EQ(buffy.tx_tail, 0);

  TEST_EQ(buffy.tx_overflow_counter, 0);
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 16 - 5 - 3 - 1);
  TEST_EQ(buffy.tx_overflow_counter, 1);

  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 0);
  TEST_EQ(buffy.tx_overflow_counter, 2);

  buffy.tx_tail = 1;
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 1);
  TEST_EQ(buffy.tx_overflow_counter, 3);
}

void test_tx_get_buffer_free(void) {
  INSTANTIATE_BUFFY(buffy);
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 15);
  TEST_EQ(buffy_tx(&buffy, "wahhh", 5), 5);
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 10);
  TEST_EQ(buffy_tx(&buffy, "foo", 3), 3);
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 7);
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 16 - 5 - 3 - 1);
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 0);
  buffy.tx_tail = 1;
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 1);
  buffy.tx_tail = 5;
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 5);
  TEST_EQ(buffy_tx(&buffy, "hi", 2), 2);
  TEST_EQ(buffy_tx_get_buffer_free(&buffy), 3);
}

void test_tx_buffer_read(void) {
  INSTANTIATE_BUFFY(buffy);
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 15);

  char out[16];
  TEST_EQ(15, buffy_tx_buffer_read(&buffy, out, 16));
  TEST_EQ(0, memcmp(out, "123456789abcdef", 15));

  TEST_EQ(buffy_tx(&buffy, "feefoo", 6), 6);
  TEST_EQ(buffy_tx(&buffy, "bar", 3), 3);

  TEST_EQ(9, buffy_tx_buffer_read(&buffy, out, 16));
  TEST_EQ(0, memcmp(out, "feefoobar", 9));
}

void test_rx(void) {
  INSTANTIATE_BUFFY(buffy);

  char buf[8];

  for (int i = 0; i < BUFFY_RX_BUF_SIZE; i++) {
    buffy.rx_buf[i] = 'a' + i;
  }

  TEST_EQ(buffy_rx(&buffy, buf, 8), 0);

  buffy.rx_head = 2;

  TEST_EQ(buffy_rx(&buffy, buf, 8), 2);
  TEST_EQ(buf[0], 'a');
  TEST_EQ(buf[1], 'b');

  buffy.rx_head = 1;

  TEST_EQ(buffy_rx(&buffy, buf, 8), 7);
  TEST_EQ(buf[0], 'c');
  TEST_EQ(buf[5], 'h');
  TEST_EQ(buf[6], 'a');
}

TEST_LIST = {{"test_tx", test_tx},
             {"text_rx", test_rx},
             {"test_tx_buffer_read", test_tx_buffer_read},
             {"test_tx_get_buffer_free", test_tx_get_buffer_free},
             {0}};
