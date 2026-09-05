#include "ui.h"
#include "pins.h"
#include "config.h"
#include "control.h"
#include "net.h"
#include <U8g2lib.h>
#include <WiFi.h>

static U8G2_SSD1306_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);
static int screen = 0;
static const int NSCREENS = 5;
static uint32_t lastActivity = 0, lastDraw = 0;
static bool sleeping = false;
static uint32_t btnDownMs = 0; static bool btnWas = false, longDone = false, emergDone = false;

void uiBegin() {
  pinMode(PIN_BTN, INPUT_PULLUP);
  u8g2.begin();
  u8g2.setContrast(128);
  lastActivity = millis();
}

static void line(int y, const char* s) { u8g2.drawStr(0, y, s); }

static void draw(const Snapshot& s) {
  char b[40];
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x12_tf);
  int ox = ((millis() / 600000) % 3) - 1;   // зсув проти випалювання
  u8g2.setDisplayRotation(U8G2_R0);
  (void)ox;
  if (s.fault[0]) {
    u8g2.setFont(u8g2_font_10x20_tf); line(20, "FAULT"); u8g2.setFont(u8g2_font_6x12_tf); line(36, s.fault);
    snprintf(b, 40, "%lus", (unsigned long)(s.uptime - s.faultSince)); line(50, b);
    u8g2.sendBuffer(); return;
  }
  switch (screen) {
    case 0:
      snprintf(b, 40, "%s", stName(s.state)); line(10, b);
      snprintf(b, 40, "B1 %5.2fV %6.2fA %s", s.b[0].u, s.b[0].i, swName(s.b[0].sw)); line(24, b);
      snprintf(b, 40, "B2 %5.2fV %6.2fA %s", s.b[1].u, s.b[1].i, swName(s.b[1].sw)); line(36, b);
      if (isnan(s.b[0].soc)) snprintf(b, 40, "SoC  --   "); else snprintf(b, 40, "SoC %3.0f%% ", s.b[0].soc);
      if (!isnan(s.b[1].soc)) { char c[12]; snprintf(c, 12, "%3.0f%%", s.b[1].soc); strncat(b, c, 39 - strlen(b)); } else strncat(b, " --", 39 - strlen(b));
      line(48, b);
      snprintf(b, 40, "LOAD %5.2fV %5.2fA", s.loadU, s.loadI); line(60, b);
      break;
    case 1:
      snprintf(b, 40, "DPS %s K%d", s.dps.ok ? (s.dps.on ? "ON" : "off") : "--", s.dps.k); line(10, b);
      snprintf(b, 40, "set %5.2fV %5.2fA", s.dps.uset, s.dps.iset); line(24, b);
      snprintf(b, 40, "out %5.2fV %5.2fA %s", s.dps.uout, s.dps.iout, s.dps.cc ? "CC" : "CV"); line(36, b);
      snprintf(b, 40, "in  %5.2fV prot %d", s.dps.uin, s.dps.prot); line(48, b);
      snprintf(b, 40, "%s", stName(s.state)); line(60, b);
      break;
    case 2:
      line(10, "cycle   in     out");
      snprintf(b, 40, "B1 %7.2f %7.2fAh", s.b[0].ahIn, s.b[0].ahOut); line(24, b);
      snprintf(b, 40, "B2 %7.2f %7.2fAh", s.b[1].ahIn, s.b[1].ahOut); line(36, b);
      snprintf(b, 40, "tot1 %6.0f/%6.0f", s.b[0].ahInTot, s.b[0].ahOutTot); line(48, b);
      snprintf(b, 40, "tot2 %6.0f/%6.0f", s.b[1].ahInTot, s.b[1].ahOutTot); line(60, b);
      break;
    case 3:
      if (isnan(s.b[0].t)) snprintf(b, 40, "T1  --"); else snprintf(b, 40, "T1 %5.1fC", s.b[0].t); line(10, b);
      if (isnan(s.b[1].t)) snprintf(b, 40, "T2  --"); else snprintf(b, 40, "T2 %5.1fC", s.b[1].t); line(24, b);
      snprintf(b, 40, "cycles %lu / %lu", (unsigned long)s.b[0].cycles, (unsigned long)s.b[1].cycles); line(36, b);
      { int y = 48; for (uint32_t bit = 1; bit && y <= 60; bit <<= 1) if (s.warn & bit) { line(y, warnName(bit)); y += 12; } }
      break;
    case 4:
      snprintf(b, 40, "%s", WiFi.SSID().c_str()); line(10, b);
      snprintf(b, 40, "%s", WiFi.localIP().toString().c_str()); line(24, b);
      snprintf(b, 40, "RSSI %d  sink %s", s.rssi, netSinkOk() ? "ok" : "--"); line(36, b);
      snprintf(b, 40, "%s", cfg().sink_url[0] ? cfg().sink_url : "(no sink)"); b[21] = 0; line(48, b);
      snprintf(b, 40, "up %lus", (unsigned long)s.uptime); line(60, b);
      break;
  }
  u8g2.sendBuffer();
}

void uiTick() {
  uint32_t now = millis();
  bool down = digitalRead(PIN_BTN) == LOW;
  if (down && !btnWas) { btnDownMs = now; longDone = emergDone = false; }
  if (down && btnWas) {
    if (!longDone && now - btnDownMs >= 2000) { longDone = true; screen = 0; lastActivity = now; }
    if (!emergDone && screen == 0 && now - btnDownMs >= 5000) {
      emergDone = true; String e; JsonDocument d;
      controlCmd("charge_stop", d.as<JsonVariantConst>(), e);
      d["bat"] = 1; d["on"] = false; controlCmd("switch", d.as<JsonVariantConst>(), e);
      d["bat"] = 2; controlCmd("switch", d.as<JsonVariantConst>(), e);
    }
  }
  if (!down && btnWas) {
    if (now - btnDownMs >= 30 && now - btnDownMs < 1000) { if (sleeping) { /* лише розбудити */ } else screen = (screen + 1) % NSCREENS; }
    lastActivity = now;
  }
  btnWas = down;

  bool shouldSleep = now - lastActivity > cfg().oled_timeout_s * 1000UL;
  Snapshot s; snapshotGet(s);
  if (s.fault[0]) shouldSleep = false;
  if (shouldSleep != sleeping) { sleeping = shouldSleep; u8g2.setPowerSave(sleeping ? 1 : 0); }
  if (!sleeping && now - lastDraw >= 500) { lastDraw = now; draw(s); }
}
