#include "control.h"
#include "pins.h"
#include "config.h"
#include "dps5015.h"
#include "measure.h"
#include "net.h"
#include "version.h"
#include <Preferences.h>

static St st = St::BOOT;
static uint32_t stSince = 0;
static char faultCode[20] = "";
static uint32_t faultSince = 0;
static uint32_t warnCtl = 0;

static bool swWant[2] = {false, false};      // що командує прошивка
static uint8_t swState[2] = {SW_OFF, SW_OFF}; // що показуємо (з forced)
static uint8_t kNow = 0;                      // 0 / 1 / 2
static bool dpsWantOn = false;
static uint32_t dpsCmdMs = 0;
static float usetNow = 0;
static uint32_t usetAdjMs = 0;
static uint32_t tailSince = 0, restUntil = 0, uinOkSince = 0;
static uint32_t lowSince[2] = {0, 0}, forcedSince[2] = {0, 0}, mismSince = 0, sumSince = 0, stuckSince = 0;
static volatile bool faultIsr = false;
static DpsMeas dpsM;

const char* stName(St s) {
  static const char* n[] = {"BOOT", "IDLE", "CHG_B1_CC", "CHG_B1_CV", "CHG_B2_BULK", "CHG_B2_ABS", "CHG_B2_FLOAT", "REST", "NO_INPUT", "FAULT"};
  return n[(int)s];
}
const char* swName(uint8_t s) { return s == SW_ON ? "on" : s == SW_FORCED ? "forced" : "off"; }
const char* warnName(uint32_t bit) {
  switch (bit) {
    case W_SENSOR_MISMATCH: return "sensor_mismatch"; case W_U_MISMATCH: return "u_mismatch";
    case W_SUM_MISMATCH: return "sum_mismatch"; case W_ZERO_DRIFT: return "zero_drift";
    case W_SW_FORCED: return "sw_forced"; case W_DPS_CRC: return "dps_crc"; case W_T_MISSING: return "t_missing";
    case W_SOC_STALE: return "soc_stale"; case W_NVS_WRITE_FAIL: return "nvs_write_fail"; case W_BUFFER_DROP: return "buffer_drop";
  }
  return "?";
}

static void IRAM_ATTR onFault() {
  digitalWrite(PIN_SW1_ON, LOW); digitalWrite(PIN_SW2_ON, LOW);
  digitalWrite(PIN_K1, LOW); digitalWrite(PIN_K2, LOW);
  faultIsr = true;
}

static void applySw() {
  digitalWrite(PIN_SW1_ON, swWant[0] ? HIGH : LOW);
  digitalWrite(PIN_SW2_ON, swWant[1] ? HIGH : LOW);
}
static void saveSwState() {
  Preferences p;
  if (p.begin("ctl", false)) { p.putBool("sw1", swWant[0]); p.putBool("sw2", swWant[1]); p.putUInt("t", millis()); p.end(); }
}

void controlBegin() {
  // Безпечний старт: рівні до pinMode
  digitalWrite(PIN_SW1_ON, LOW); digitalWrite(PIN_SW2_ON, LOW); digitalWrite(PIN_K1, LOW); digitalWrite(PIN_K2, LOW);
  pinMode(PIN_SW1_ON, OUTPUT); pinMode(PIN_SW2_ON, OUTPUT); pinMode(PIN_K1, OUTPUT); pinMode(PIN_K2, OUTPUT);
  pinMode(PIN_FAULT, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_FAULT), onFault, FALLING);
  stSince = millis();
}

static void setState(St s, const char* reason) {
  if (s == st) return;
  char frag[200];
  snprintf(frag, sizeof(frag), "\"from\":\"%s\",\"to\":\"%s\",\"reason\":\"%s\",\"data\":{\"duration_s\":%lu}",
           stName(st), stName(s), reason, (unsigned long)((millis() - stSince) / 1000));
  st = s; stSince = millis(); tailSince = 0;
  eventEmit("state", frag);
  measureSaveCounters();
}

// Реле — лише при вимкненому виході й нульовому струмі
static bool relaySet(uint8_t k) {
  if (k == kNow) return true;
  const DpsRegs& r = dpsRegs();
  if (r.valid && (r.onoff || r.iout > 0)) return false;
  digitalWrite(PIN_K1, LOW); digitalWrite(PIN_K2, LOW);
  delay(30);
  if (k == 1) digitalWrite(PIN_K1, HIGH);
  if (k == 2) digitalWrite(PIN_K2, HIGH);
  kNow = k;
  delay(50);
  return true;
}

static bool dpsOff() {
  dpsWantOn = false; dpsCmdMs = millis();
  if (!dpsSetOutput(false)) return false;
  for (int i = 0; i < 20; i++) { delay(100); if (dpsPoll() && dpsRegs().onoff == 0 && dpsRegs().iout == 0 && dpsRegs().uout < 100) return true; }
  return false;
}

static void allOff(const char* why) {
  swWant[0] = swWant[1] = false; applySw();
  dpsSetOutput(false); dpsWantOn = false;
  digitalWrite(PIN_K1, LOW); digitalWrite(PIN_K2, LOW); kNow = 0;
  saveSwState();
  (void)why;
}

static void enterFault(const char* code, const char* detail) {
  allOff(code);
  strlcpy(faultCode, code, sizeof(faultCode)); faultSince = millis();
  char frag[160];
  snprintf(frag, sizeof(frag), "\"data\":{\"code\":\"%s\",\"detail\":\"%s\"}", code, detail ? detail : "");
  eventEmit("fault", frag);
  setState(St::FAULT, "fault");
}

// Профіль поточного стану
static float targetU() {
  Config& c = cfg();
  float t2 = measureT(2);
  float tc = isnan(t2) ? 0 : c.pb.tc_v_per_c * (t2 - c.pb.t_ref);
  switch (st) {
    case St::CHG_B1_CC: case St::CHG_B1_CV: return c.li.u_cv;
    case St::CHG_B2_BULK: case St::CHG_B2_ABS: return c.pb.u_abs + tc;
    case St::CHG_B2_FLOAT: return c.pb.u_float + tc;
    default: return 0;
  }
}
static float targetI() {
  Config& c = cfg();
  return (stChargingBat(st) == 1) ? c.li.i_cc : c.pb.i_bulk;
}

static bool tempAllows(int bat) {
  Config& c = cfg();
  float t = measureT(bat);
  if (isnan(t)) return bat == 2;               // свинець без датчика — можна (без компенсації); LiFePO₄ — ні
  float tmin = bat == 1 ? c.li.t_min : -40, tmax = bat == 1 ? c.li.t_max : c.pb.t_max;
  return t >= tmin && t <= tmax;
}

// Старт заряду гілки — послідовність з dps5015-modbus.md
static int chargeStart(int bat, String& err) {
  if (st == St::FAULT) { err = "fault active"; return 423; }
  if (st == St::NO_INPUT) { err = "no input"; return 409; }
  if (stIsCharging(st)) { err = "already charging"; return 409; }
  if (!dpsRegs().valid) { err = "dps offline"; return 409; }
  if (!tempAllows(bat)) { err = "temperature"; return 409; }
  if (!dpsOff()) { err = "dps did not turn off"; return 409; }
  if (!relaySet(bat)) { err = "relay"; return 409; }
  float ub = measureU(bat);
  float tgt = (bat == 1) ? cfg().li.u_cv : cfg().pb.u_abs;
  usetNow = min(ub + 0.5f, tgt + 0.6f);
  float iset = (bat == 1) ? cfg().li.i_cc : cfg().pb.i_bulk;
  if (!dpsSetUI(usetNow, iset)) { err = "dps write"; return 409; }
  if (!dpsSetOutput(true)) { err = "dps on"; return 409; }
  dpsWantOn = true; dpsCmdMs = millis(); usetAdjMs = millis();
  setState(bat == 1 ? St::CHG_B1_CC : St::CHG_B2_BULK, "user");
  return 200;
}
static void chargeStop(const char* reason) {
  dpsOff();
  relaySet(0);
  setState(St::IDLE, reason);
}

void controlAfterInit() {
  // DPS міг лишитись увімкненим після нашого ресету
  if (dpsPoll() && dpsRegs().onoff) dpsSetOutput(false);
  // Відновлення ключів, якщо ресет був < 60 с тому
  Preferences p;
  bool restored = false;
  if (p.begin("ctl", true)) {
    uint32_t t = p.getUInt("t", 0);
    if (t && esp_reset_reason() != ESP_RST_POWERON && millis() < 60000) {
      swWant[0] = p.getBool("sw1", false); swWant[1] = p.getBool("sw2", false); restored = true;
    }
    p.end();
  }
  applySw();
  char frag[120];
  snprintf(frag, sizeof(frag), "\"data\":{\"fw\":\"%s\",\"reset_reason\":%d,\"restored\":%s}", FW_VERSION, (int)esp_reset_reason(), restored ? "true" : "false");
  eventEmit("boot", frag);
  st = St::IDLE; stSince = millis();
}

St controlState() { return st; }

static void updateDpsMeas() {
  const DpsRegs& r = dpsRegs();
  dpsM.ok = r.valid;
  dpsM.uin = r.uin / 100.0f; dpsM.uout = r.uout / 100.0f; dpsM.iout = r.iout / 100.0f;
  dpsM.uset = r.uset / 100.0f; dpsM.iset = r.iset / 100.0f;
  dpsM.on = r.onoff; dpsM.cc = r.cvcc; dpsM.prot = r.prot; dpsM.k = kNow;
}

static void tick() {
  uint32_t now = millis();
  Config& c = cfg();
  dpsPoll();
  updateDpsMeas();
  const DpsRegs& r = dpsRegs();
  int chg = stChargingBat(st);
  float u1 = measureU(1), u2 = measureU(2), i1 = measureI(1), i2 = measureI(2);
  Snapshot m; measureFill(m);

  // 1. Апаратна засувка FAULT
  if (faultIsr) { faultIsr = false; if (st != St::FAULT) enterFault("OC_LATCH", "sensor fault latch"); }

  // 2. DPS не відповідає → NO_INPUT (найімовірніше зник БЖ — DPS без нього мовчить)
  if (r.failStreak >= 3 && st != St::FAULT && st != St::NO_INPUT) { allOff("dps_timeout"); setState(St::NO_INPUT, "dps_timeout"); }
  if (r.valid) {
    if (r.uin < 3000 && st != St::FAULT && st != St::NO_INPUT) { allOff("no_input"); setState(St::NO_INPUT, "no_input"); }
    if (r.prot != 0 && st != St::FAULT) { char d[24]; snprintf(d, 24, "prot=%u", r.prot); enterFault("DPS_PROTECT", d); }
    // Розбіжність стану виходу
    if (now - dpsCmdMs > 2000 && st != St::FAULT && ((bool)r.onoff != dpsWantOn)) enterFault("DPS_STATE_MISMATCH", r.onoff ? "dps on unexpectedly" : "dps off unexpectedly");
    // Реле розімкнені, а DPS віддає струм
    if (kNow == 0 && r.iout > 50) { if (!stuckSince) stuckSince = now; else if (now - stuckSince > 5000 && st != St::FAULT) enterFault("RELAY_STUCK", "current with relays open"); }
    else stuckSince = 0;
  }

  // 3. NO_INPUT → IDLE
  if (st == St::NO_INPUT) {
    if (r.valid && r.uin >= 3100) { if (!uinOkSince) uinOkSince = now; else if (now - uinOkSince > 10000) { uinOkSince = 0; setState(St::IDLE, "input_back"); } }
    else uinOkSince = 0;
  }

  // 4. Заряд: фази й завершення
  if (chg) {
    float ub = chg == 1 ? u1 : u2, ib = chg == 1 ? i1 : i2;
    float tgt = targetU();
    if (!tempAllows(chg)) chargeStop("t_out_of_range");
    else {
      if (st == St::CHG_B1_CC && ub >= tgt - 0.05f) setState(St::CHG_B1_CV, "u_reached");
      if (st == St::CHG_B2_BULK && ub >= tgt - 0.05f) setState(St::CHG_B2_ABS, "u_reached");
      if (st == St::CHG_B1_CV) {
        if (ib <= c.li.i_tail) { if (!tailSince) tailSince = now; else if (now - tailSince > 60000) { measureMarkFull(1); chargeStop("tail_current"); restUntil = now + c.rest_min * 60000UL; } }
        else tailSince = 0;
      }
      if (st == St::CHG_B2_ABS) {
        bool done = false;
        if (ib <= c.pb.i_abs_end) { if (!tailSince) tailSince = now; else if (now - tailSince > 60000) done = true; } else tailSince = 0;
        if (now - stSince > 4UL * 3600000UL) done = true;
        if (done) { measureMarkFull(2); setState(St::CHG_B2_FLOAT, ib <= c.pb.i_abs_end ? "tail_current" : "timeout"); }
      }
      if (st == St::CHG_B2_FLOAT && now - stSince > 24UL * 3600000UL) chargeStop("timeout");
      // Підтягування U-SET у фазах утримання напруги; у CC/BULK — фіксований запас
      if (stIsCharging(st) && now - usetAdjMs >= 2000 && r.valid) {
        usetAdjMs = now;
        float want;
        if (st == St::CHG_B1_CC || st == St::CHG_B2_BULK) want = tgt + 0.6f;
        else { float d = constrain(tgt - ub, -0.05f, 0.05f); want = constrain(usetNow + d, tgt, tgt + 1.0f); }
        want = min(want, Config::U_SET_MAX);
        if (fabsf(want - usetNow) >= 0.005f) { usetNow = want; dpsSetUI(usetNow, targetI()); }
      }
    }
  }

  // 5. REST → IDLE, авто-політика
  if (st == St::REST && now >= restUntil) setState(St::IDLE, "rest_done");
  if (st == St::IDLE && restUntil && now < restUntil) setState(St::REST, "policy");
  if (st == St::IDLE && c.policy_auto && strcmp(c.policy_order, "manual") != 0 && r.valid) {
    int pick = 0;
    auto needs = [&](int b) { float s = m.b[b - 1].soc; float u = b == 1 ? u1 : u2; float t = b == 1 ? c.li.u_cv : c.pb.u_abs;
                              return isnan(s) ? (u < t - 0.5f) : (s < 95); };
    if (!strcmp(c.policy_order, "b1_first")) pick = needs(1) ? 1 : needs(2) ? 2 : 0;
    else if (!strcmp(c.policy_order, "b2_first")) pick = needs(2) ? 2 : needs(1) ? 1 : 0;
    else { float s1 = isnan(m.b[0].soc) ? u1 : m.b[0].soc, s2 = isnan(m.b[1].soc) ? u2 : m.b[1].soc;
           int first = s1 <= s2 ? 1 : 2, second = 3 - first; pick = needs(first) ? first : needs(second) ? second : 0; }
    if (pick) { String e; if (chargeStart(pick, e) == 200) setState(pick == 1 ? St::CHG_B1_CC : St::CHG_B2_BULK, "policy"); }
  }

  // 6. Ключі: пороги розряду, forced
  for (int b = 0; b < 2; b++) {
    float u = b ? u2 : u1, i = b ? i2 : i1;
    if (swWant[b] && u < c.dis[b].u_off) { if (!lowSince[b]) lowSince[b] = now; else if (now - lowSince[b] > 5000) { swWant[b] = false; applySw(); saveSwState(); char f[80]; snprintf(f, 80, "\"data\":{\"bat\":%d,\"sw\":\"off\",\"by\":\"u_low\"}", b + 1); eventEmit("switch", f); } }
    else lowSince[b] = 0;
    bool forced = !swWant[b] && chg != b + 1 && kNow != b + 1 && fabsf(i) > 0.3f;
    if (forced) { if (!forcedSince[b]) forcedSince[b] = now; } else forcedSince[b] = 0;
    uint8_t ns = swWant[b] ? SW_ON : (forcedSince[b] && now - forcedSince[b] > 5000) ? SW_FORCED : SW_OFF;
    if (ns != swState[b]) { bool wasForced = swState[b] == SW_FORCED; swState[b] = ns; if (ns == SW_FORCED || wasForced) { char f[80]; snprintf(f, 80, "\"data\":{\"bat\":%d,\"sw\":\"%s\",\"by\":\"detect\"}", b + 1, swName(ns)); eventEmit("switch", f); } }
  }
  if (swState[0] == SW_FORCED || swState[1] == SW_FORCED) warnCtl |= W_SW_FORCED; else warnCtl &= ~W_SW_FORCED;
  measureSetContext(swState[0], swState[1], chg);

  // 7. Перехресні перевірки
  if (chg && r.valid && r.onoff) {
    float ib = chg == 1 ? i1 : i2, io = r.iout / 100.0f, ub = chg == 1 ? u1 : u2, uo = r.uout / 100.0f;
    bool mis = fabsf(ib - io) > 0.5f + 0.05f * io;
    if (mis) { if (!mismSince) mismSince = now; else if (now - mismSince > 10000) warnCtl |= W_SENSOR_MISMATCH; } else { mismSince = 0; warnCtl &= ~W_SENSOR_MISMATCH; }
    if (fabsf(uo - ub) > 1.0f) warnCtl |= W_U_MISMATCH; else warnCtl &= ~W_U_MISMATCH;
  } else { mismSince = 0; warnCtl &= ~(W_SENSOR_MISMATCH | W_U_MISMATCH); }
  {
    float dis = 0; if (i1 < 0) dis -= i1; if (i2 < 0) dis -= i2;
    bool mis = fabsf(dis - m.loadI) > 0.5f + 0.1f * m.loadI;
    if (mis) { if (!sumSince) sumSince = now; else if (now - sumSince > 10000) warnCtl |= W_SUM_MISMATCH; } else { sumSince = 0; warnCtl &= ~W_SUM_MISMATCH; }
  }
  if (r.crcErrors && r.crcErrors % 10 == 1) warnCtl |= W_DPS_CRC; else warnCtl &= ~W_DPS_CRC;
}

void controlTickOnce() { tick(); }

void controlFill(Snapshot& s) {
  s.state = st; strlcpy(s.fault, faultCode, sizeof(s.fault)); s.faultSince = faultSince / 1000;
  s.dps = dpsM; s.warn |= warnCtl;
  s.b[0].sw = swState[0]; s.b[1].sw = swState[1];
}

void snapshotGet(Snapshot& s) {
  s = Snapshot();
  measureFill(s);
  controlFill(s);
  s.rssi = netRssi();
  s.uptime = millis() / 1000;
}

int controlCmd(const char* cmd, JsonVariantConst a, String& err) {
  if (!strcmp(cmd, "charge_start")) { int bat = a["bat"] | 0; if (bat != 1 && bat != 2) { err = "bat"; return 400; } return chargeStart(bat, err); }
  if (!strcmp(cmd, "charge_stop")) { if (!stIsCharging(st)) { err = "not charging"; return 409; } chargeStop("user"); return 200; }
  if (!strcmp(cmd, "switch")) {
    int bat = a["bat"] | 0; if (bat != 1 && bat != 2) { err = "bat"; return 400; }
    if (!a["on"].is<bool>()) { err = "on"; return 400; }
    if (st == St::FAULT) { err = "fault active"; return 423; }
    bool on = a["on"];
    swWant[bat - 1] = on; applySw(); saveSwState();
    char f[80]; snprintf(f, 80, "\"data\":{\"bat\":%d,\"sw\":\"%s\",\"by\":\"user\"}", bat, on ? "on" : "off"); eventEmit("switch", f);
    return 200;
  }
  if (!strcmp(cmd, "fault_clear")) {
    if (st != St::FAULT) { err = "no fault"; return 409; }
    if (!strcmp(faultCode, "OC_LATCH")) { measureSensorPower(false); delay(100); measureSensorPower(true); delay(50); if (digitalRead(PIN_FAULT) == LOW) { err = "fault still active"; return 409; } }
    if (!strcmp(faultCode, "DPS_PROTECT")) { dpsPoll(); if (dpsRegs().prot) { err = "dps still in protect"; return 409; } }
    faultCode[0] = 0; eventEmit("fault_cleared", "");
    setState(St::IDLE, "user");
    return 200;
  }
  if (!strcmp(cmd, "calibrate_zero")) { int ch = a["ch"] | 0; if (!measureCalibZero(ch)) { err = "ch"; return 400; } eventEmit("calibration", "\"data\":{\"what\":\"zero\"}"); return 200; }
  if (!strcmp(cmd, "calibrate_gain")) { if (!measureCalibGain(a["ch"] | 0, a["i_ref"] | 0.0f)) { err = "ch/i_ref or no current"; return 400; } eventEmit("calibration", "\"data\":{\"what\":\"gain\"}"); return 200; }
  if (!strcmp(cmd, "calibrate_ugain")) {
    int ch = a["ch"] | 0; if (a["ch"].is<const char*>() && !strcmp(a["ch"], "load")) ch = 3;
    if (!measureCalibUGain(ch, a["u_ref"] | 0.0f)) { err = "ch/u_ref"; return 400; } eventEmit("calibration", "\"data\":{\"what\":\"ugain\"}"); return 200;
  }
  if (!strcmp(cmd, "soc_set")) { int bat = a["bat"] | 0; if (bat < 1 || bat > 2 || !a["soc"].is<float>()) { err = "bat/soc"; return 400; } measureSetSoc(bat, a["soc"]); return 200; }
  if (!strcmp(cmd, "counters_reset")) { int bat = a["bat"] | 0; if (bat < 1 || bat > 2) { err = "bat"; return 400; } const char* w = a["what"] | "cycle"; measureResetCounters(bat, !strcmp(w, "total")); return 200; }
  if (!strcmp(cmd, "reboot")) { measureSaveCounters(); delay(200); ESP.restart(); return 200; }
  err = "unknown cmd"; return 400;
}
