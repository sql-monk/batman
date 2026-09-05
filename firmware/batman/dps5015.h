// DPS5015 по Modbus RTU — docs/dps5015-modbus.md. Власна мінімальна реалізація
// (0x03 / 0x06 / 0x10), таймаут 200 мс, щоб не блокувати керування.
#pragma once
#include <Arduino.h>

struct DpsRegs {
  uint16_t uset = 0, iset = 0, uout = 0, iout = 0, power = 0, uin = 0, lock = 0, prot = 0, cvcc = 0, onoff = 0;
  bool valid = false;
  uint32_t lastOkMs = 0;
  uint8_t failStreak = 0;   // невдалих обмінів поспіль
  uint32_t crcErrors = 0;
};

void dpsBegin();
bool dpsPoll();                         // читає 0x0000..0x0009 у dpsRegs()
const DpsRegs& dpsRegs();
bool dpsRead(uint16_t reg, uint16_t n, uint16_t* out);
bool dpsWrite(uint16_t reg, uint16_t val);
bool dpsWriteMany(uint16_t reg, const uint16_t* vals, uint16_t n);
bool dpsSetOutput(bool on);
bool dpsSetUI(float u, float i);        // із жорсткою стелею I_SET_MAX / U_SET_MAX
bool dpsWriteM0Safe();                  // група M0: старт із вимкненим виходом
