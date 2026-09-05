#include "dps5015.h"
#include "pins.h"
#include "config.h"

static const uint8_t  DPS_ADDR = 1;
static const uint32_t DPS_TIMEOUT_MS = 200;
static DpsRegs g_regs;
static HardwareSerial& S = Serial2;

const DpsRegs& dpsRegs() { return g_regs; }

static uint16_t crc16(const uint8_t* d, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= d[i];
    for (int b = 0; b < 8; b++) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

static void flushRx() { while (S.available()) S.read(); }

// Надіслати кадр, отримати відповідь очікуваної довжини. Повертає к-сть байт або 0.
static size_t xfer(uint8_t* frame, size_t n, uint8_t* resp, size_t expect) {
  uint16_t c = crc16(frame, n);
  frame[n] = c & 0xFF; frame[n + 1] = c >> 8;
  flushRx();
  S.write(frame, n + 2);
  S.flush();
  uint32_t t0 = millis();
  size_t got = 0;
  while (millis() - t0 < DPS_TIMEOUT_MS && got < expect) {
    if (S.available()) { resp[got++] = S.read(); t0 = millis(); }
    else delay(1);
  }
  if (got < expect) { g_regs.failStreak = min<uint8_t>(g_regs.failStreak + 1, 250); return 0; }
  uint16_t rc = resp[got - 2] | (resp[got - 1] << 8);
  if (rc != crc16(resp, got - 2) || resp[0] != DPS_ADDR) {
    g_regs.crcErrors++;
    g_regs.failStreak = min<uint8_t>(g_regs.failStreak + 1, 250);
    return 0;
  }
  g_regs.failStreak = 0;
  g_regs.lastOkMs = millis();
  return got;
}

void dpsBegin() {
  S.begin(9600, SERIAL_8N1, PIN_DPS_RX, PIN_DPS_TX);
}

bool dpsRead(uint16_t reg, uint16_t n, uint16_t* out) {
  uint8_t f[8] = { DPS_ADDR, 0x03, (uint8_t)(reg >> 8), (uint8_t)reg, (uint8_t)(n >> 8), (uint8_t)n };
  uint8_t r[5 + 2 * 16];
  if (n > 16) return false;
  size_t got = xfer(f, 6, r, 5 + 2 * n);
  if (!got || r[1] != 0x03 || r[2] != 2 * n) return false;
  for (uint16_t i = 0; i < n; i++) out[i] = (r[3 + 2 * i] << 8) | r[4 + 2 * i];
  return true;
}

bool dpsWrite(uint16_t reg, uint16_t val) {
  uint8_t f[8] = { DPS_ADDR, 0x06, (uint8_t)(reg >> 8), (uint8_t)reg, (uint8_t)(val >> 8), (uint8_t)val };
  uint8_t r[8];
  size_t got = xfer(f, 6, r, 8);
  return got && r[1] == 0x06;
}

bool dpsWriteMany(uint16_t reg, const uint16_t* vals, uint16_t n) {
  if (n > 8) return false;
  uint8_t f[9 + 16];
  f[0] = DPS_ADDR; f[1] = 0x10; f[2] = reg >> 8; f[3] = reg; f[4] = n >> 8; f[5] = n; f[6] = 2 * n;
  for (uint16_t i = 0; i < n; i++) { f[7 + 2 * i] = vals[i] >> 8; f[8 + 2 * i] = vals[i]; }
  uint8_t r[8];
  size_t got = xfer(f, 7 + 2 * n, r, 8);
  return got && r[1] == 0x10;
}

bool dpsPoll() {
  uint16_t v[10];
  if (!dpsRead(0x0000, 10, v)) { g_regs.valid = g_regs.failStreak < 3; return false; }
  g_regs.uset = v[0]; g_regs.iset = v[1]; g_regs.uout = v[2]; g_regs.iout = v[3]; g_regs.power = v[4];
  g_regs.uin = v[5]; g_regs.lock = v[6]; g_regs.prot = v[7]; g_regs.cvcc = v[8]; g_regs.onoff = v[9];
  g_regs.valid = true;
  return true;
}

bool dpsSetOutput(bool on) { return dpsWrite(0x0009, on ? 1 : 0); }

bool dpsSetUI(float u, float i) {
  if (u > Config::U_SET_MAX) u = Config::U_SET_MAX;
  if (i > Config::I_SET_MAX) i = Config::I_SET_MAX;
  if (u < 0) u = 0; if (i < 0) i = 0;
  uint16_t v[2] = { (uint16_t)lroundf(u * 100), (uint16_t)lroundf(i * 100) };
  return dpsWriteMany(0x0000, v, 2);
}

bool dpsWriteM0Safe() {
  // U-SET 20,00 В, I-SET 1,00 А, OVP 31,00 В, OCP 12,50 А; S-INI (0x0057) = 0
  uint16_t v[4] = { 2000, 100, 3100, 1250 };
  if (!dpsWriteMany(0x0050, v, 4)) return false;
  return dpsWrite(0x0057, 0);
}
