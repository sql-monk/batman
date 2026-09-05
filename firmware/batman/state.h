// Спільні типи: стани, знімок вимірювань, коди попереджень/відмов.
#pragma once
#include <Arduino.h>

enum class St : uint8_t {
  BOOT, IDLE, CHG_B1_CC, CHG_B1_CV, CHG_B2_BULK, CHG_B2_ABS, CHG_B2_FLOAT,
  REST, NO_INPUT, FAULT
};
const char* stName(St s);
inline bool stIsCharging(St s) { return s >= St::CHG_B1_CC && s <= St::CHG_B2_FLOAT; }
inline int  stChargingBat(St s) {
  if (s == St::CHG_B1_CC || s == St::CHG_B1_CV) return 1;
  if (s == St::CHG_B2_BULK || s == St::CHG_B2_ABS || s == St::CHG_B2_FLOAT) return 2;
  return 0;
}

enum SwState : uint8_t { SW_OFF = 0, SW_ON = 1, SW_FORCED = 2 };
const char* swName(uint8_t s);

// Попередження — бітова маска
enum Warn : uint32_t {
  W_SENSOR_MISMATCH = 1u << 0, W_U_MISMATCH = 1u << 1, W_SUM_MISMATCH = 1u << 2,
  W_ZERO_DRIFT = 1u << 3, W_SW_FORCED = 1u << 4, W_DPS_CRC = 1u << 5,
  W_T_MISSING = 1u << 6, W_SOC_STALE = 1u << 7, W_NVS_WRITE_FAIL = 1u << 8,
  W_BUFFER_DROP = 1u << 9,
};
const char* warnName(uint32_t bit);

struct BatMeas {
  float u = 0, i = 0, t = NAN;
  float soc = NAN;
  uint8_t sw = SW_OFF;
  double ahIn = 0, ahOut = 0, whIn = 0, whOut = 0;          // за цикл
  double ahInTot = 0, ahOutTot = 0, whInTot = 0, whOutTot = 0; // усього
  uint32_t cycles = 0;
};

struct DpsMeas {
  bool ok = false;
  float uin = 0, uout = 0, iout = 0, uset = 0, iset = 0;
  bool on = false, cc = false;
  uint8_t prot = 0;
  uint8_t k = 0;   // 0 — реле розімкнені, 1/2 — K1/K2
};

struct Snapshot {
  BatMeas b[2];
  float loadU = 0, loadI = 0;
  DpsMeas dps;
  St state = St::BOOT;
  char fault[20] = "";
  uint32_t faultSince = 0;
  uint32_t warn = 0;
  int rssi = 0;
  uint32_t uptime = 0;
};

// Черга подій у мережу (control/measure -> net)
void eventEmit(const char* event, const char* json_data /* об'єкт без дужок-оболонки або "" */);
