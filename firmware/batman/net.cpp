#include "net.h"
#include "config.h"
#include "control.h"
#include "measure.h"
#include "dps5015.h"
#include "version.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <ESPmDNS.h>
#include <WebServer.h>
#include <HTTPClient.h>
#include <Update.h>
#include <ArduinoJson.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

static WebServer server(80);
static WiFiUDP udp;
static bool apMode = false;
static uint32_t seq = 0;
static bool sinkOk = false;
static uint32_t lastTelemetryMs = 0, lastRetryMs = 0, lastWifiTryMs = 0;
static uint32_t wifiBackoffMs = 1000;
static SemaphoreHandle_t bufMtx;

// Буфери: телеметрія і події окремо (події не витісняються)
static const int TBUF = 60, EBUF = 50;
static String tbuf[TBUF]; static int tHead = 0, tCount = 0;
static String ebuf[EBUF]; static int eHead = 0, eCount = 0;
static uint32_t dropped = 0;

uint32_t netNextSeq() { return ++seq; }
int netRssi() { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }
bool netSinkOk() { return sinkOk; }

static void pushT(const String& s) {
  xSemaphoreTake(bufMtx, portMAX_DELAY);
  if (tCount == TBUF) { tHead = (tHead + 1) % TBUF; tCount--; dropped++; }
  tbuf[(tHead + tCount) % TBUF] = s; tCount++;
  xSemaphoreGive(bufMtx);
}
static void pushE(const String& s) {
  xSemaphoreTake(bufMtx, portMAX_DELAY);
  if (eCount == EBUF) { eHead = (eHead + 1) % EBUF; eCount--; dropped++; }
  ebuf[(eHead + eCount) % EBUF] = s; eCount++;
  xSemaphoreGive(bufMtx);
}

void eventEmit(const char* event, const char* fragment) {
  String s; s.reserve(256);
  s += "{\"v\":1,\"type\":\"event\",\"id\":\"" + deviceId() + "\",\"seq\":" + String(netNextSeq()) +
       ",\"uptime\":" + String(millis() / 1000) + ",\"event\":\"" + event + "\"";
  if (fragment && fragment[0]) { s += ","; s += fragment; }
  s += "}";
  Serial.printf("[EV] %s\n", s.c_str());
  pushE(s);
}

// ---------- JSON ----------
static void batJson(JsonObject o, const BatMeas& b) {
  o["u"] = serialized(String(b.u, 2)); o["i"] = serialized(String(b.i, 2));
  if (isnan(b.t)) o["t"] = nullptr; else o["t"] = serialized(String(b.t, 1));
  if (isnan(b.soc)) o["soc"] = nullptr; else o["soc"] = serialized(String(b.soc, 1));
  o["sw"] = swName(b.sw);
  o["ah_in"] = serialized(String(b.ahIn, 3)); o["ah_out"] = serialized(String(b.ahOut, 3));
  o["wh_in"] = serialized(String(b.whIn, 1)); o["wh_out"] = serialized(String(b.whOut, 1));
  o["ah_in_tot"] = serialized(String(b.ahInTot, 1)); o["ah_out_tot"] = serialized(String(b.ahOutTot, 1));
  o["cycles"] = b.cycles;
}
static void telemetryJson(JsonDocument& d, bool withSeq) {
  Snapshot s; snapshotGet(s);
  d["v"] = 1; d["type"] = "telemetry"; d["id"] = deviceId();
  if (withSeq) d["seq"] = netNextSeq();
  d["uptime"] = s.uptime; d["state"] = stName(s.state);
  batJson(d["b1"].to<JsonObject>(), s.b[0]);
  batJson(d["b2"].to<JsonObject>(), s.b[1]);
  d["load"]["u"] = serialized(String(s.loadU, 2)); d["load"]["i"] = serialized(String(s.loadI, 2));
  JsonObject p = d["dps"].to<JsonObject>();
  p["ok"] = s.dps.ok; p["uin"] = serialized(String(s.dps.uin, 2)); p["uout"] = serialized(String(s.dps.uout, 2));
  p["iout"] = serialized(String(s.dps.iout, 2)); p["uset"] = serialized(String(s.dps.uset, 2)); p["iset"] = serialized(String(s.dps.iset, 2));
  p["on"] = s.dps.on; p["cc"] = s.dps.cc; p["prot"] = s.dps.prot; p["k"] = s.dps.k;
  if (s.fault[0]) { d["fault"]["code"] = s.fault; d["fault"]["since"] = s.faultSince; } else d["fault"] = nullptr;
  d["wifi"]["rssi"] = s.rssi;
  JsonArray w = d["warn"].to<JsonArray>();
  for (uint32_t bit = 1; bit; bit <<= 1) if (s.warn & bit) w.add(warnName(bit));
  if (dropped) w.add("buffer_drop");
}
static void statusJson(JsonDocument& d) {
  Snapshot s; snapshotGet(s);
  d["id"] = deviceId(); d["fw"] = FW_VERSION; d["v"] = 1; d["uptime"] = s.uptime; d["state"] = stName(s.state);
  if (s.fault[0]) d["fault"] = s.fault; else d["fault"] = nullptr;
  d["sink"]["url"] = cfg().sink_url; d["sink"]["interval_s"] = cfg().sink_interval_s; d["sink"]["ok"] = sinkOk;
  d["sink"]["buffered"] = tCount + eCount; d["sink"]["dropped"] = dropped;
  d["wifi"]["ssid"] = WiFi.SSID(); d["wifi"]["ip"] = WiFi.localIP().toString(); d["wifi"]["rssi"] = s.rssi; d["wifi"]["ap"] = apMode;
  d["heap"] = ESP.getFreeHeap(); d["min_heap"] = ESP.getMinFreeHeap();
  d["reset_reason"] = (int)esp_reset_reason();
  d["dps"]["crc_errors"] = dpsRegs().crcErrors; d["dps"]["ok"] = dpsRegs().valid;
  d["ads_ok"] = measureAdsOk();
}

// ---------- HTTP ----------
static void sendJson(int code, JsonDocument& d) { String s; serializeJson(d, s); server.send(code, "application/json", s); }
static void sendOk() { server.send(200, "application/json", "{\"ok\":true}"); }
static void sendErr(int code, const String& e) { server.send(code, "application/json", "{\"ok\":false,\"error\":\"" + e + "\"}"); }

static const char* PAGE =
"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>batman</title>"
"<style>body{font-family:sans-serif;max-width:640px;margin:1em auto;padding:0 1em}pre{background:#eee;padding:.5em;overflow:auto}"
"button{margin:.2em}input{width:100%;margin:.2em 0}</style><h2>batman %ID%</h2><pre id=s>…</pre>"
"<div><button onclick=\"c('charge_start',{bat:1})\">Заряд B1</button><button onclick=\"c('charge_start',{bat:2})\">Заряд B2</button>"
"<button onclick=\"c('charge_stop',{})\">Стоп</button><button onclick=\"c('switch',{bat:1,on:true})\">SW1 on</button>"
"<button onclick=\"c('switch',{bat:1,on:false})\">SW1 off</button><button onclick=\"c('switch',{bat:2,on:true})\">SW2 on</button>"
"<button onclick=\"c('switch',{bat:2,on:false})\">SW2 off</button><button onclick=\"c('fault_clear',{})\">Скинути FAULT</button></div>"
"<h3>Wi-Fi / сервіс</h3><form method=post action=/setup>SSID<input name=ssid>Пароль<input name=pass type=password>"
"Sink URL<input name=sink placeholder='http://192.168.1.10:8000/api/ingest'><button>Зберегти й перезавантажити</button></form>"
"<script>async function r(){let t=await fetch('/telemetry');document.getElementById('s').textContent=JSON.stringify(await t.json(),null,1)}"
"async function c(cmd,a){a.cmd=cmd;let x=await fetch('/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(a)});alert(await x.text());r()}"
"r();setInterval(r,2000)</script>";

static void setupRoutes() {
  server.on("/", HTTP_GET, []() { String p = PAGE; p.replace("%ID%", deviceId()); server.send(200, "text/html", p); });
  server.on("/setup", HTTP_POST, []() {
    Config& c = cfg();
    if (server.hasArg("ssid")) strlcpy(c.wifi_ssid, server.arg("ssid").c_str(), sizeof(c.wifi_ssid));
    if (server.hasArg("pass") && server.arg("pass").length()) strlcpy(c.wifi_pass, server.arg("pass").c_str(), sizeof(c.wifi_pass));
    if (server.hasArg("sink")) strlcpy(c.sink_url, server.arg("sink").c_str(), sizeof(c.sink_url));
    cfgSave(); server.send(200, "text/plain", "saved, rebooting"); delay(500); ESP.restart();
  });
  server.on("/status", HTTP_GET, []() { JsonDocument d; statusJson(d); sendJson(200, d); });
  server.on("/telemetry", HTTP_GET, []() { JsonDocument d; telemetryJson(d, false); sendJson(200, d); });
  server.on("/events", HTTP_GET, []() {
    uint32_t since = server.hasArg("since") ? server.arg("since").toInt() : 0;
    String out = "[";
    xSemaphoreTake(bufMtx, portMAX_DELAY);
    bool first = true;
    for (int i = 0; i < eCount; i++) { const String& e = ebuf[(eHead + i) % EBUF]; int p = e.indexOf("\"seq\":"); uint32_t sq = p >= 0 ? e.substring(p + 6).toInt() : 0; if (sq > since) { if (!first) out += ","; out += e; first = false; } }
    xSemaphoreGive(bufMtx);
    out += "]"; server.send(200, "application/json", out);
  });
  server.on("/sink", HTTP_POST, []() {
    JsonDocument d; if (deserializeJson(d, server.arg("plain"))) { sendErr(400, "json"); return; }
    if (!d["url"].is<const char*>()) { sendErr(400, "url"); return; }
    Config& c = cfg(); strlcpy(c.sink_url, d["url"], sizeof(c.sink_url));
    if (d["token"].is<const char*>()) strlcpy(c.sink_token, d["token"], sizeof(c.sink_token));
    int iv = d["interval_s"] | c.sink_interval_s; c.sink_interval_s = constrain(iv, 1, 60);
    cfgSave(); sinkOk = false; sendOk();
  });
  server.on("/sink", HTTP_DELETE, []() { cfg().sink_url[0] = 0; cfgSave(); sinkOk = false; sendOk(); });
  server.on("/config", HTTP_GET, []() { JsonDocument d; cfgToJson(d.to<JsonObject>()); sendJson(200, d); });
  server.on("/config", HTTP_POST, []() {
    JsonDocument d; if (deserializeJson(d, server.arg("plain"))) { sendErr(400, "json"); return; }
    String err, changed;
    if (!cfgFromJson(d.as<JsonVariantConst>(), err, changed)) { sendErr(400, err); return; }
    if (changed.length()) { String f = "\"data\":{\"changed\":\"" + changed + "\"}"; eventEmit("config", f.c_str()); }
    JsonDocument o; cfgToJson(o.to<JsonObject>()); sendJson(200, o);
  });
  server.on("/control", HTTP_POST, []() {
    JsonDocument d; if (deserializeJson(d, server.arg("plain"))) { sendErr(400, "json"); return; }
    const char* cmd = d["cmd"] | ""; String err;
    int code = controlCmd(cmd, d.as<JsonVariantConst>(), err);
    if (code == 200) sendOk(); else sendErr(code, err);
  });
  server.on("/calibration", HTTP_GET, []() { JsonDocument d; measureCalToJson(d.to<JsonObject>()); sendJson(200, d); });
  server.on("/update", HTTP_POST, []() {
    bool ok = !Update.hasError();
    server.send(ok ? 200 : 500, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"update\"}");
    if (ok) { delay(2000); ESP.restart(); }
  }, []() {
    HTTPUpload& up = server.upload();
    if (up.status == UPLOAD_FILE_START) { measureSaveCounters(); Update.begin(UPDATE_SIZE_UNKNOWN); }
    else if (up.status == UPLOAD_FILE_WRITE) Update.write(up.buf, up.currentSize);
    else if (up.status == UPLOAD_FILE_END) Update.end(true);
  });
  server.onNotFound([]() { sendErr(404, "not found"); });
  server.begin();
}

// ---------- Wi-Fi ----------
static void startAp() {
  apMode = true;
  WiFi.mode(WIFI_AP);
  String ssid = "batman-" + deviceId();
  WiFi.softAP(ssid.c_str(), "batmanbat");
  Serial.printf("[net] AP %s 192.168.4.1\n", ssid.c_str());
}
static void startSta() {
  apMode = false;
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(("batman-" + deviceId()).c_str());
  WiFi.begin(cfg().wifi_ssid, cfg().wifi_pass);
  lastWifiTryMs = millis();
}
static void onConnected() {
  Serial.printf("[net] IP %s RSSI %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
  String host = "batman-" + deviceId();
  if (MDNS.begin(host.c_str())) {
    MDNS.addService("batman", "tcp", 80);
    MDNS.addServiceTxt("batman", "tcp", "id", deviceId());
    MDNS.addServiceTxt("batman", "tcp", "fw", FW_VERSION);
    MDNS.addServiceTxt("batman", "tcp", "v", "1");
  }
  udp.begin(47474);
  wifiBackoffMs = 1000;
}

void netBegin() {
  bufMtx = xSemaphoreCreateMutex();
  if (cfg().wifi_ssid[0]) startSta(); else startAp();
  setupRoutes();
}

// ---------- телеметрія ----------
static bool postBatch() {
  if (!cfg().sink_url[0] || WiFi.status() != WL_CONNECTED) return false;
  String body; body.reserve(2048); body = "[";
  int nT = 0, nE = 0; bool first = true;
  xSemaphoreTake(bufMtx, portMAX_DELAY);
  for (int i = 0; i < eCount && nE < 50; i++, nE++) { if (!first) body += ","; body += ebuf[(eHead + i) % EBUF]; first = false; }
  for (int i = 0; i < tCount && nT < 50; i++, nT++) { if (!first) body += ","; body += tbuf[(tHead + i) % TBUF]; first = false; }
  xSemaphoreGive(bufMtx);
  body += "]";
  if (nT + nE == 0) return true;
  HTTPClient http; http.setTimeout(3000);
  http.begin(cfg().sink_url); http.addHeader("Content-Type", "application/json");
  if (cfg().sink_token[0]) http.addHeader("Authorization", String("Bearer ") + cfg().sink_token);
  int code = http.POST(body); http.end();
  if (code >= 200 && code < 300) {
    xSemaphoreTake(bufMtx, portMAX_DELAY);
    eHead = (eHead + nE) % EBUF; eCount -= nE; tHead = (tHead + nT) % TBUF; tCount -= nT;
    xSemaphoreGive(bufMtx);
    sinkOk = true; return true;
  }
  sinkOk = false; return false;
}

static void udpTick() {
  int n = udp.parsePacket();
  if (n <= 0) return;
  char buf[32]; int l = udp.read(buf, sizeof(buf) - 1); buf[l > 0 ? l : 0] = 0;
  if (strncmp(buf, "BATMAN?", 7)) return;
  String r = "{\"v\":1,\"id\":\"" + deviceId() + "\",\"ip\":\"" + WiFi.localIP().toString() + "\",\"port\":80,\"fw\":\"" FW_VERSION "\"}";
  udp.beginPacket(udp.remoteIP(), udp.remotePort()); udp.print(r); udp.endPacket();
}

void netTask(void*) {
  static bool wasConnected = false;
  for (;;) {
    server.handleClient();
    if (!apMode) {
      bool conn = WiFi.status() == WL_CONNECTED;
      if (conn && !wasConnected) onConnected();
      if (!conn && millis() - lastWifiTryMs > wifiBackoffMs) { WiFi.disconnect(); WiFi.begin(cfg().wifi_ssid, cfg().wifi_pass); lastWifiTryMs = millis(); wifiBackoffMs = min<uint32_t>(wifiBackoffMs * 2, 60000); }
      wasConnected = conn;
      if (conn) {
        udpTick();
        uint32_t iv = cfg().sink_interval_s * 1000UL;
        if (cfg().sink_url[0] && millis() - lastTelemetryMs >= iv) {
          lastTelemetryMs = millis();
          JsonDocument d; telemetryJson(d, true); String s; serializeJson(d, s); pushT(s);
        }
        if ((tCount || eCount) && (sinkOk || millis() - lastRetryMs > 5000)) { lastRetryMs = millis(); postBatch(); }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}
