/*
 * Vitallic status display - Arduino UNO Q (optional part of the build).
 * Shows what the dog just found on the UNO Q's built-in 8x13 LED matrix,
 * so judges can see the result on the dog itself.
 *
 * The Linux side (python/main.py) polls the laptop running field_scan.py
 * and calls show(code) over the Bridge. No wiring needed.
 */
#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>

Arduino_LED_Matrix matrix;
const int ROWS = 8;
const int COLS = 13;
uint8_t frame[ROWS * COLS];  // brightness 0-7 per pixel (3 grayscale bits)

enum State { IDLE = 0, SCAN = 1, MINE = 2, FRAG = 3, RESCAN = 4, NO_TARGET = 5 };
volatile int state = IDLE;

void show(int code) {  // called from Linux over the Bridge
  state = code;
}

void px(int r, int c, uint8_t v) {
  if (r >= 0 && r < ROWS && c >= 0 && c < COLS) frame[r * COLS + c] = v;
}

void drawIdle(unsigned long t) {  // slow breathing dot
  uint8_t v = (t / 200) % 8;
  px(3, 6, v);
  px(4, 6, v);
}

void drawScan(unsigned long t) {  // bar sweeping left and right
  int span = 2 * (COLS - 1);
  int c = (t / 70) % span;
  if (c >= COLS) c = span - c;
  for (int r = 0; r < ROWS; r++) {
    px(r, c, 7);
    px(r, c - 1, 2);
    px(r, c + 1, 2);
  }
}

void drawMine(unsigned long t) {  // flashing X: send a human
  if ((t / 250) % 2) return;
  for (int i = 0; i < ROWS; i++) {
    px(i, 2 + i, 7);
    px(i, 10 - i, 7);
  }
}

void drawFragment() {  // check mark: scrap, low priority
  const int pts[][2] = {{4, 2}, {5, 3}, {6, 4}, {5, 5}, {4, 6}, {3, 7}, {2, 8}, {1, 9}, {0, 10}};
  for (auto &p : pts) px(p[0], p[1], 7);
}

void drawRescan(unsigned long t) {  // blinking question mark
  if ((t / 500) % 2) return;
  const int pts[][2] = {{0, 5}, {0, 6}, {0, 7}, {1, 4}, {1, 8}, {2, 8}, {3, 7}, {4, 6}, {5, 6}, {7, 6}};
  for (auto &p : pts) px(p[0], p[1], 7);
}

void drawNoTarget() {  // dim dash: nothing ferrous here
  for (int c = 4; c <= 8; c++) {
    px(3, c, 3);
    px(4, c, 3);
  }
}

void setup() {
  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();
  Bridge.begin();
  Bridge.provide("show", show);
}

void loop() {
  unsigned long t = millis();
  memset(frame, 0, sizeof(frame));
  switch (state) {
    case SCAN:      drawScan(t);     break;
    case MINE:      drawMine(t);     break;
    case FRAG:      drawFragment();  break;
    case RESCAN:    drawRescan(t);   break;
    case NO_TARGET: drawNoTarget();  break;
    default:        drawIdle(t);     break;
  }
  matrix.draw(frame);
  delay(20);
}
