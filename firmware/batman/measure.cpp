#include "measure.h"
#include "pins.h"
#include "config.h"
#include <Wire.h>
#include <ADS1X15.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

static ADS1115 ads(I2C_ADDR_ADS);
static OneWire ow(PIN_OW);
static DallasTemperature ds(&ow);
static SemaphoreHandle_t mtx;
static bool adsOk = false;

// Калібрування
struct Cal { float vzero[3] = {ACS_ZERO_V, ACS_ZERO_V, ACS_ZERO_V}; float gcal[3] = {1, 1, 1}; float ugcal[3] = {1, 1, 1}; };
static Cal cal;
static bool calDirty = false;
static uint32_t calSavedMs = 0;

// Лічильники (NVS "cnt")
struct Cnt {
  double ahIn[2] = {0, 0}, ahOut[2] = {0, 0}, whIn[2] = {0, 0}, whOut[2] = {0, 0};
  double ahInTot[2] = {0, 0}, ahOutTot[2] = {0, 0}, whInTot[2] = {0, 0}, whOutTot[2] = {0, 0};
  uint32_t cycles[2] = {0, 0};
  float soc[2] = {NAN, NAN};
  uint32_t fullAgeS[2] = {0, 0};   // секунд від останнього «100 %»
};
static Cnt cnt;
static uint32_t cntSavedMs = 0;

// Живі величини
static float vRaw[4] = {0, 0, 0, 0};          // останні напруги на входах ADS
static float iAvg[2] = {0, 0}, uAvg[2] = {0, 0};  // EMA ~1 с / ~2 с
static float iEma30[2] = {ACS_ZERO_V, ACS_ZERO_V};   // EMA ~30 с сирої напруги для автонуля
static float iPrev[2] = {0, 0};
static uint32_t tPrevUs[2] = {0, 0};
static bool havePrev[2] = {false, false};
static float loadU = 0, loadI = 0;
static float tBat[2] = {NAN, NAN};
static uint32_t warnBits = 0;

// Контекст автонуля
static uint8_t ctxSw[2] = {SW_OFF, SW_OFF};
static int ctxChg = 0;
static uint32_t zeroCondSince[2] = {0, 0};

static void calLoad() {
  Preferences p;
  if (!p.begin("cal", true)) return;
  for (int i = 0; i < 3; i++) {
    char k[8];
    snprintf(k, 8, "vz%d", i); cal.vzero[i] = p.getFloat(k, cal.vzero[i]);
    snprintf(k, 8, "gc%d", i); cal.gcal[i] = p.getFloat(k, cal.gcal[i]);
    snprintf(k, 8, "ug%d", i); cal.ugcal[i] = p.getFloat(k, cal.ugcal[i]);
  }
  p.end();
}
static bool calSave() {
  Preferences p;
  if (!p.begin("cal", false)) { warnBits |= W_NVS_WRITE_FAIL; return false; }
  for (int i = 0; i < 3; i++) {
    char k[8];
    snprintf(k, 8, "vz%d", i); p.putFloat(k, cal.vzero[i]);
    snprintf(k, 8, "gc%d", i); p.putFloat(k, cal.gcal[i]);
    snprintf(k, 8, "ug%d", i); p.putFloat(k, cal.ugcal[i]);
  }
  p.end();
  calDirty = false; calSavedMs = millis();
  return true;
}
static void cntLoad() {
  Preferences p;
  if (!p.begin("cnt", true)) return;
  for (int b = 0; b < 2; b++) {
    char k[8];
    snprintf(k, 8, "ai%d", b);  cnt.ahIn[b] = p.getDouble(k, 0);
    snprintf(k, 8, "ao%d", b);  cnt.ahOut[b] = p.getDouble(k, 0);
    snprintf(k, 8, "wi%d", b);  cnt.whIn[b] = p.getDouble(k, 0);
    snprintf(k, 8, "wo%d", b);  cnt.whOut[b] = p.getDouble(k, 0);
    snprintf(k, 8, "ait%d", b); cnt.ahInTot[b] = p.getDouble(k, 0);
    snprintf(k, 8, "aot%d", b); cnt.ahOutTot[b] = p.getDouble(k, 0);
    snprintf(k, 8, "wit%d", b); cnt.whInTot[b] = p.getDouble(k, 0);
    snprintf(k, 8, "wot%d", b); cnt.whOutTot[b] = p.getDouble(k, 0);
    snprintf(k, 8, "cy%d", b);  cnt.cycles[b] = p.getUInt(k, 0);
    snprintf(k, 8, "soc%d", b); cnt.soc[b] = p.getFloat(k, NAN);
    snprintf(k, 8, "fa%d", b);  cnt.fullAgeS[b] = p.getUInt(k, 0);
  }
  p.end();
}
void measureSaveCounters() {
  Preferences p;
  if (!p.begin("cnt", false)) { warnBits |= W_NVS_WRITE_FAIL; return; }
  xSemaphoreTake(mtx, portMAX_DELAY);
  Cnt c = cnt;
  xSemaphoreGive(mtx);
  for (int b = 0; b < 2; b++) {
    char k[8];
    snprintf(k, 8, "ai%d", b);  p.putDouble(k, c.ahIn[b]);
    snprintf(k, 8, "ao%d", b);  p.putDouble(k, c.ahOut[b]);
    snprintf(k, 8, "wi%d", b);  p.putDouble(k, c.whIn[b]);
    snprintf(k, 8, "wo%d", b);  p.putDouble(k, c.whOut[b]);
    snprintf(k, 8, "ait%d", b); p.putDouble(k, c.ahInTot[b]);
    snprintf(k, 8, "aot%d", b); p.putDouble(k, c.ahOutTot[b]);
    snprintf(k, 8, "wit%d", b); p.putDouble(k, c.whInTot[b]);
    snprintf(k, 8, "wot%d", b); p.putDouble(k, c.whOutTot[b]);
    snprintf(k, 8, "cy%d", b);  p.putUInt(k, c.cycles[b]);
    snprintf(k, 8, "soc%d", b); p.putFloat(k, c.soc[b]);
    snprintf(k, 8, "fa%d", b);  p.putUInt(k, c.fullAgeS[b]);
  }
  p.end();
  cntSavedMs = millis();
}

void measureSensorPower(bool on) { digitalWrite(PIN_SENS_PWR, on ? LOW : HIGH); }

void measureBegin() {
  mtx = xSemaphoreCreateMutex();
  pinMode(PIN_SENS_PWR, OUTPUT);
  measureSensorPower(false);
  calLoad();
  cntLoad();
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  adsOk = ads.begin() && ads.isConnected();
  if (adsOk) {
    ads.setGain(1);        // ±4,096 В
    ads.setDataRate(6);    // 475 SPS
    ads.setMode(1);        // одиночні перетворення
  }
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_U_LOAD, ADC_11db);
  analogSetPinAttenuation(PIN_I_LOAD, ADC_11db);
  ds.begin();
  ds.setResolution(12);
  ds.setWaitForConversion(false);
  measureSensorPower(true);
  delay(100);
}

bool measureAdsOk() { return adsOk; }

static inline float rawToI(int b, float v) { return (v - cal.vzero[b]) / ACS_SENS_V_PER_A * cal.gcal[b]; }

// Один відлік струму гілки b (0/1): інтегрування трапеціями
static void integrate(int b, float i, uint32_t tUs) {
  if (havePrev[b]) {
    double dt = (double)(uint32_t)(tUs - tPrevUs[b]) / 1e6;   // с
    if (dt > 0 && dt < 1.0) {
      double q = (i + iPrev[b]) / 2.0 * dt;                    // А·с
      double u = uAvg[b];
      Config& c = cfg();
      double eta = (b == 0) ? 0.98 : 0.90;
      if (q > 0) { cnt.ahIn[b] += q / 3600; cnt.whIn[b] += q * u / 3600; cnt.ahInTot[b] += q / 3600; cnt.whInTot[b] += q * u / 3600;
                   if (!isnan(cnt.soc[b])) cnt.soc[b] += q / 3600 * eta / c.c_nom[b] * 100; }
      else       { cnt.ahOut[b] -= q / 3600; cnt.whOut[b] -= q * u / 3600; cnt.ahOutTot[b] -= q / 3600; cnt.whOutTot[b] -= q * u / 3600;
                   if (!isnan(cnt.soc[b])) cnt.soc[b] += q / 3600 / c.c_nom[b] * 100; }
      if (!isnan(cnt.soc[b])) cnt.soc[b] = constrain(cnt.soc[b], 0.0f, 100.0f);
    }
  }
  iPrev[b] = i; tPrevUs[b] = tUs; havePrev[b] = true;
}

void measureTask(void*) {
  const float aI = 1.0f / 118;      // EMA ≈ 1 с при ~118 відл/с
  const float aU = 1.0f / 236;      // ≈ 2 с
  const float a30 = 1.0f / 3540;    // ≈ 30 с
  for (;;) {
    if (!adsOk) { vTaskDelay(pdMS_TO_TICKS(500)); adsOk = ads.isConnected(); continue; }
    for (int ch = 0; ch < 4; ch++) {
      int16_t raw = ads.readADC(ch);
      float v = ads.toVoltage(raw);
      uint32_t t = micros();
      xSemaphoreTake(mtx, portMAX_DELAY);
      vRaw[ch] = v;
      if (ch < 2) {
        float i = rawToI(ch, v);
        iAvg[ch] += aI * (i - iAvg[ch]);
        iEma30[ch] += a30 * (v - iEma30[ch]);
        integrate(ch, i, t);
      } else {
        float u = v * DIV_UB * cal.ugcal[ch - 2];
        uAvg[ch - 2] += aU * (u - uAvg[ch - 2]);
      }
      xSemaphoreGive(mtx);
    }
    taskYIELD();
  }
}

// Автонуль — раз на секунду зі slow-тіку
static void autozeroTick() {
  uint32_t now = millis();
  for (int b = 0; b < 2; b++) {
    int o = 1 - b;
    bool cond = ctxSw[b] == SW_OFF && ctxChg != b + 1 && uAvg[o] > uAvg[b] + 0.3f;
    if (!cond) { zeroCondSince[b] = 0; continue; }
    if (!zeroCondSince[b]) { zeroCondSince[b] = now; continue; }
    if (now - zeroCondSince[b] >= 30000) {
      xSemaphoreTake(mtx, portMAX_DELAY);
      cal.vzero[b] += 0.1f * (iEma30[b] - cal.vzero[b]);
      xSemaphoreGive(mtx);
      calDirty = true;
      zeroCondSince[b] = now;   // наступна корекція через 30 с
    }
  }
  bool drift = false;
  for (int b = 0; b < 3; b++) if (fabsf(cal.vzero[b] - ACS_ZERO_V) > 0.05f) drift = true;
  if (drift) warnBits |= W_ZERO_DRIFT; else warnBits &= ~W_ZERO_DRIFT;
  if (calDirty && millis() - calSavedMs > 3600000UL) calSave();
}

static bool dsRequested = false;
void measureSlowTick() {
  // ADC1: середнє з 16
  uint32_t su = 0, si = 0;
  for (int k = 0; k < 16; k++) { su += analogReadMilliVolts(PIN_U_LOAD); si += analogReadMilliVolts(PIN_I_LOAD); }
  float vu = su / 16.0f / 1000, vi = si / 16.0f / 1000;
  float lu = vu * DIV_ULOAD * cal.ugcal[2];
  float li = (cal.vzero[2] - vi) / ACS_SENS_V_PER_A * cal.gcal[2];   // навантаження нижче центру
  if (li < 0) li = 0;
  // DS18B20 асинхронно
  if (dsRequested) {
    float t0 = ds.getTempCByIndex(0), t1 = ds.getTempCByIndex(1);
    tBat[0] = (t0 == DEVICE_DISCONNECTED_C || t0 < -50) ? NAN : t0;
    tBat[1] = (t1 == DEVICE_DISCONNECTED_C || t1 < -50) ? NAN : t1;
    if (isnan(tBat[0]) || isnan(tBat[1])) warnBits |= W_T_MISSING; else warnBits &= ~W_T_MISSING;
  }
  ds.requestTemperatures();
  dsRequested = true;
  xSemaphoreTake(mtx, portMAX_DELAY);
  loadU = lu; loadI = li;
  for (int b = 0; b < 2; b++) cnt.fullAgeS[b]++;
  bool stale = false;
  for (int b = 0; b < 2; b++) if (!isnan(cnt.soc[b]) && cnt.fullAgeS[b] > 7UL * 86400) stale = true;
  xSemaphoreGive(mtx);
  if (stale) warnBits |= W_SOC_STALE; else warnBits &= ~W_SOC_STALE;
  autozeroTick();
  if (millis() - cntSavedMs > 600000UL) measureSaveCounters();
}

void measureFill(Snapshot& s) {
  xSemaphoreTake(mtx, portMAX_DELAY);
  for (int b = 0; b < 2; b++) {
    BatMeas& m = s.b[b];
    m.u = uAvg[b]; m.i = iAvg[b]; m.t = tBat[b];
    m.soc = (!isnan(cnt.soc[b]) && cnt.fullAgeS[b] <= 7UL * 86400) ? cnt.soc[b] : NAN;
    m.ahIn = cnt.ahIn[b]; m.ahOut = cnt.ahOut[b]; m.whIn = cnt.whIn[b]; m.whOut = cnt.whOut[b];
    m.ahInTot = cnt.ahInTot[b]; m.ahOutTot = cnt.ahOutTot[b]; m.whInTot = cnt.whInTot[b]; m.whOutTot = cnt.whOutTot[b];
    m.cycles = cnt.cycles[b];
  }
  s.loadU = loadU; s.loadI = loadI;
  s.warn |= warnBits;
  xSemaphoreGive(mtx);
}

void measureSetContext(uint8_t sw1, uint8_t sw2, int chargingBat) { ctxSw[0] = sw1; ctxSw[1] = sw2; ctxChg = chargingBat; }

float measureU(int bat) { return uAvg[bat - 1]; }
float measureI(int bat) { return iAvg[bat - 1]; }
float measureT(int bat) { return tBat[bat - 1]; }

bool measureCalibZero(int ch) {
  if (ch < 1 || ch > 3) return false;
  if (ch == 3) {
    uint32_t s = 0; for (int k = 0; k < 64; k++) { s += analogReadMilliVolts(PIN_I_LOAD); delay(5); }
    cal.vzero[2] = s / 64.0f / 1000;
  } else {
    // середнє за 5 с із сирих відліків
    double acc = 0; int n = 0; uint32_t t0 = millis();
    while (millis() - t0 < 5000) { acc += vRaw[ch - 1]; n++; delay(10); }
    cal.vzero[ch - 1] = acc / n;
  }
  return calSave();
}
bool measureCalibGain(int ch, float iRef) {
  if (ch < 1 || ch > 3 || iRef <= 0) return false;
  if (ch == 3) { if (loadI <= 0.05f) return false; cal.gcal[2] *= iRef / loadI; }
  else { float iraw = iAvg[ch - 1] / cal.gcal[ch - 1]; if (fabsf(iraw) < 0.05f) return false; cal.gcal[ch - 1] = fabsf(iRef / iraw); }
  return calSave();
}
bool measureCalibUGain(int ch, float uRef) {
  if (ch < 1 || ch > 3 || uRef <= 0) return false;
  if (ch == 3) { if (loadU < 1) return false; cal.ugcal[2] *= uRef / loadU; }
  else { if (uAvg[ch - 1] < 1) return false; cal.ugcal[ch - 1] *= uRef / uAvg[ch - 1]; }
  return calSave();
}
void measureSetSoc(int bat, float soc) {
  xSemaphoreTake(mtx, portMAX_DELAY);
  cnt.soc[bat - 1] = constrain(soc, 0.0f, 100.0f); cnt.fullAgeS[bat - 1] = 0;
  xSemaphoreGive(mtx);
  measureSaveCounters();
}
void measureResetCounters(int bat, bool total) {
  int b = bat - 1;
  xSemaphoreTake(mtx, portMAX_DELAY);
  cnt.ahIn[b] = cnt.ahOut[b] = cnt.whIn[b] = cnt.whOut[b] = 0;
  if (total) { cnt.ahInTot[b] = cnt.ahOutTot[b] = cnt.whInTot[b] = cnt.whOutTot[b] = 0; cnt.cycles[b] = 0; }
  xSemaphoreGive(mtx);
  measureSaveCounters();
}
void measureMarkFull(int bat) {
  int b = bat - 1;
  char frag[160];
  xSemaphoreTake(mtx, portMAX_DELAY);
  snprintf(frag, sizeof(frag), "\"data\":{\"bat\":%d,\"ah_in\":%.3f,\"ah_out\":%.3f,\"wh_in\":%.1f,\"wh_out\":%.1f,\"cycles\":%lu}",
           bat, cnt.ahIn[b], cnt.ahOut[b], cnt.whIn[b], cnt.whOut[b], (unsigned long)(cnt.cycles[b] + 1));
  cnt.ahIn[b] = cnt.ahOut[b] = cnt.whIn[b] = cnt.whOut[b] = 0;
  cnt.cycles[b]++; cnt.soc[b] = 100; cnt.fullAgeS[b] = 0;
  xSemaphoreGive(mtx);
  eventEmit("cycle_complete", frag);
  measureSaveCounters();
}
void measureCalToJson(JsonObject o) {
  JsonArray z = o["zero_v"].to<JsonArray>(), g = o["gain"].to<JsonArray>(), ug = o["ugain"].to<JsonArray>();
  for (int i = 0; i < 3; i++) { z.add(cal.vzero[i]); g.add(cal.gcal[i]); ug.add(cal.ugcal[i]); }
}
