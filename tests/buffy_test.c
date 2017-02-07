#include "buffy.h"

#include <stdio.h>

#include <cutest.h>

#define TEST_EQ(a, b)                          \
  do {                                         \
    typeof(a) _a = (a);                        \
    typeof(b) _b = (b);                        \
    TEST_CHECK_(_a == _b, "%d != %d", _a, _b); \
  } while (0)

void test_tx(void) {
  INSTANTIATE_BUFFY(buffy);
  TEST_CHECK(buffy.tx_head == 0);
  TEST_CHECK(buffy.tx_tail == 0);

  TEST_CHECK(buffy_tx(&buffy, "wahhh", 5) == 5);
  TEST_CHECK(buffy.tx_head == 5);
  TEST_CHECK(buffy.tx_tail == 0);

  TEST_CHECK(buffy_tx(&buffy, "foo", 3) == 3);
  TEST_CHECK(buffy.tx_head == 8);
  TEST_CHECK(buffy.tx_tail == 0);

  TEST_EQ(buffy.tx_overflow_counter, 0);
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 16 - 5 - 3 - 1);
  TEST_EQ(buffy.tx_overflow_counter, 1);

  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 0);
  TEST_EQ(buffy.tx_overflow_counter, 2);

  buffy.tx_tail = 1;
  TEST_EQ(buffy_tx(&buffy, "123456789abcdef", 16), 1);
  TEST_EQ(buffy.tx_overflow_counter, 3);
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

TEST_LIST = {{"test_tx", test_tx}, {"text_rx", test_rx}, {0}};