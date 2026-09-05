// Вимірювання й підрахунок — docs/measurement.md
#pragma once
#include "state.h"
#include <ArduinoJson.h>

void measureBegin();
void measureTask(void* arg);              // ADS1115 по колу, інтегрування (ядро 1)
void measureSlowTick();                   // 1 Гц: DS18B20, ADC1, NVS за розкладом
void measureFill(Snapshot& s);            // b[].u,i,t,soc,ah…; loadU, loadI; warn-біти вимірювання
void measureSetContext(uint8_t sw1, uint8_t sw2, int chargingBat);  // для автонуля
bool measureCalibZero(int ch);            // ch 1..3 (3 = навантаження)
bool measureCalibGain(int ch, float iRef);
bool measureCalibUGain(int ch, float uRef);  // ch 1, 2 або 3 = LOAD
void measureSetSoc(int bat, float soc);   // bat 1..2
void measureResetCounters(int bat, bool total);
void measureMarkFull(int bat);            // «100 %»: цикл ← 0, cycles++, soc = 100
void measureSaveCounters();
void measureSensorPower(bool on);
bool measureAdsOk();
void measureCalToJson(JsonObject o);
// Середні за 1 с (для керування) — швидкий доступ без повного знімка
float measureU(int bat);                  // bat 1..2
float measureI(int bat);
float measureT(int bat);                  // NAN, якщо немає
