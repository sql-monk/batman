#include "config.h"
#include <Preferences.h>
#include <WiFi.h>

static Config g_cfg;
Config& cfg() { return g_cfg; }

String deviceId() {
  uint64_t mac = ESP.getEfuseMac();
  char s[8];
  snprintf(s, sizeof(s), "%02x%02x%02x", (uint8_t)(mac >> 24), (uint8_t)(mac >> 32), (uint8_t)(mac >> 40));
  return String(s);
}

void cfgLoad() {
  Preferences p;
  if (!p.begin("cfg", true)) return;
  Config& c = g_cfg;
  p.getString("ssid", c.wifi_ssid, sizeof(c.wifi_ssid));
  p.getString("pass", c.wifi_pass, sizeof(c.wifi_pass));
  p.getString("sink", c.sink_url, sizeof(c.sink_url));
  p.getString("tok", c.sink_token, sizeof(c.sink_token));
  c.sink_interval_s = p.getUShort("sint", c.sink_interval_s);
  c.c_nom[0] = p.getFloat("cn1", c.c_nom[0]);
  c.c_nom[1] = p.getFloat("cn2", c.c_nom[1]);
  c.li.i_cc = p.getFloat("li_icc", c.li.i_cc);   c.li.u_cv = p.getFloat("li_ucv", c.li.u_cv);
  c.li.i_tail = p.getFloat("li_it", c.li.i_tail); c.li.t_min = p.getFloat("li_tmin", c.li.t_min);
  c.li.t_max = p.getFloat("li_tmax", c.li.t_max);
  c.pb.i_bulk = p.getFloat("pb_ib", c.pb.i_bulk); c.pb.u_abs = p.getFloat("pb_ua", c.pb.u_abs);
  c.pb.u_float = p.getFloat("pb_uf", c.pb.u_float); c.pb.i_abs_end = p.getFloat("pb_ie", c.pb.i_abs_end);
  c.pb.tc_v_per_c = p.getFloat("pb_tc", c.pb.tc_v_per_c); c.pb.t_ref = p.getFloat("pb_tr", c.pb.t_ref);
  c.pb.t_max = p.getFloat("pb_tmax", c.pb.t_max);
  c.dis[0].u_off = p.getFloat("d1off", c.dis[0].u_off); c.dis[0].u_on = p.getFloat("d1on", c.dis[0].u_on);
  c.dis[1].u_off = p.getFloat("d2off", c.dis[1].u_off); c.dis[1].u_on = p.getFloat("d2on", c.dis[1].u_on);
  c.policy_auto = p.getBool("pauto", c.policy_auto);
  p.getString("porder", c.policy_order, sizeof(c.policy_order));
  c.rest_min = p.getUShort("rest", c.rest_min);
  c.oled_timeout_s = p.getUShort("oledt", c.oled_timeout_s);
  p.end();
}

bool cfgSave() {
  Preferences p;
  if (!p.begin("cfg", false)) return false;
  Config& c = g_cfg;
  p.putString("ssid", c.wifi_ssid); p.putString("pass", c.wifi_pass);
  p.putString("sink", c.sink_url);  p.putString("tok", c.sink_token);
  p.putUShort("sint", c.sink_interval_s);
  p.putFloat("cn1", c.c_nom[0]); p.putFloat("cn2", c.c_nom[1]);
  p.putFloat("li_icc", c.li.i_cc); p.putFloat("li_ucv", c.li.u_cv); p.putFloat("li_it", c.li.i_tail);
  p.putFloat("li_tmin", c.li.t_min); p.putFloat("li_tmax", c.li.t_max);
  p.putFloat("pb_ib", c.pb.i_bulk); p.putFloat("pb_ua", c.pb.u_abs); p.putFloat("pb_uf", c.pb.u_float);
  p.putFloat("pb_ie", c.pb.i_abs_end); p.putFloat("pb_tc", c.pb.tc_v_per_c); p.putFloat("pb_tr", c.pb.t_ref);
  p.putFloat("pb_tmax", c.pb.t_max);
  p.putFloat("d1off", c.dis[0].u_off); p.putFloat("d1on", c.dis[0].u_on);
  p.putFloat("d2off", c.dis[1].u_off); p.putFloat("d2on", c.dis[1].u_on);
  p.putBool("pauto", c.policy_auto); p.putString("porder", c.policy_order);
  p.putUShort("rest", c.rest_min); p.putUShort("oledt", c.oled_timeout_s);
  p.end();
  return true;
}

void cfgToJson(JsonObject o) {
  Config& c = g_cfg;
  o["v"] = 1;
  JsonObject w = o["wifi"].to<JsonObject>();
  w["ssid"] = c.wifi_ssid; w["hostname"] = "batman-" + deviceId();
  JsonObject s = o["sink"].to<JsonObject>();
  s["url"] = c.sink_url; s["interval_s"] = c.sink_interval_s; s["token_set"] = c.sink_token[0] != 0;
  JsonObject b = o["bat"].to<JsonObject>();
  b["1"]["chem"] = "lifepo4"; b["1"]["c_nom"] = c.c_nom[0];
  b["2"]["chem"] = "pb";      b["2"]["c_nom"] = c.c_nom[1];
  JsonObject pr = o["profile"].to<JsonObject>();
  JsonObject li = pr["lifepo4"].to<JsonObject>();
  li["i_cc"] = c.li.i_cc; li["u_cv"] = c.li.u_cv; li["i_tail"] = c.li.i_tail; li["t_min"] = c.li.t_min; li["t_max"] = c.li.t_max;
  JsonObject pb = pr["pb"].to<JsonObject>();
  pb["i_bulk"] = c.pb.i_bulk; pb["u_abs"] = c.pb.u_abs; pb["u_float"] = c.pb.u_float; pb["i_abs_end"] = c.pb.i_abs_end;
  pb["tc_v_per_c"] = c.pb.tc_v_per_c; pb["t_ref"] = c.pb.t_ref; pb["t_max"] = c.pb.t_max;
  JsonObject d = o["discharge"].to<JsonObject>();
  d["1"]["u_off"] = c.dis[0].u_off; d["1"]["u_on"] = c.dis[0].u_on;
  d["2"]["u_off"] = c.dis[1].u_off; d["2"]["u_on"] = c.dis[1].u_on;
  JsonObject po = o["policy"].to<JsonObject>();
  po["charge_order"] = c.policy_order; po["auto"] = c.policy_auto; po["rest_min"] = c.rest_min;
  JsonObject lim = o["limits"].to<JsonObject>();
  lim["i_set_max"] = Config::I_SET_MAX; lim["u_set_max"] = Config::U_SET_MAX;
  o["oled"]["timeout_s"] = c.oled_timeout_s;
}

// Оновлення одного float з межами
static bool upF(JsonVariantConst v, const char* key, float& dst, float lo, float hi, String& err, String& changed, const char* path) {
  if (!v[key].is<float>()) return true;
  float x = v[key].as<float>();
  if (x < lo || x > hi) { err = String(path) + "." + key + " out of range"; return false; }
  if (x != dst) { dst = x; changed += String(path) + "." + key + ","; }
  return true;
}

bool cfgFromJson(JsonVariantConst v, String& err, String& changed) {
  Config& c = g_cfg;
  Config backup = c;
  bool ok = true;
  if (v["wifi"].is<JsonObjectConst>()) {
    JsonObjectConst w = v["wifi"];
    if (w["ssid"].is<const char*>()) { strlcpy(c.wifi_ssid, w["ssid"], sizeof(c.wifi_ssid)); changed += "wifi.ssid,"; }
    if (w["pass"].is<const char*>()) { strlcpy(c.wifi_pass, w["pass"], sizeof(c.wifi_pass)); changed += "wifi.pass,"; }
  }
  if (v["sink"].is<JsonObjectConst>()) {
    JsonObjectConst s = v["sink"];
    if (s["url"].is<const char*>()) { strlcpy(c.sink_url, s["url"], sizeof(c.sink_url)); changed += "sink.url,"; }
    if (s["token"].is<const char*>()) { strlcpy(c.sink_token, s["token"], sizeof(c.sink_token)); changed += "sink.token,"; }
    if (s["interval_s"].is<int>()) { int i = s["interval_s"]; if (i < 1 || i > 60) { err = "sink.interval_s"; ok = false; } else { c.sink_interval_s = i; changed += "sink.interval_s,"; } }
  }
  if (v["bat"].is<JsonObjectConst>()) {
    ok = ok && upF(v["bat"]["1"], "c_nom", c.c_nom[0], 1, 1000, err, changed, "bat.1");
    ok = ok && upF(v["bat"]["2"], "c_nom", c.c_nom[1], 1, 1000, err, changed, "bat.2");
  }
  if (v["profile"].is<JsonObjectConst>()) {
    JsonVariantConst li = v["profile"]["lifepo4"], pb = v["profile"]["pb"];
    ok = ok && upF(li, "i_cc", c.li.i_cc, 0.5f, Config::I_SET_MAX, err, changed, "profile.lifepo4");
    ok = ok && upF(li, "u_cv", c.li.u_cv, 27.0f, 29.4f, err, changed, "profile.lifepo4");
    ok = ok && upF(li, "i_tail", c.li.i_tail, 0.2f, 5.0f, err, changed, "profile.lifepo4");
    ok = ok && upF(li, "t_min", c.li.t_min, -20, 20, err, changed, "profile.lifepo4");
    ok = ok && upF(li, "t_max", c.li.t_max, 20, 60, err, changed, "profile.lifepo4");
    ok = ok && upF(pb, "i_bulk", c.pb.i_bulk, 0.5f, Config::I_SET_MAX, err, changed, "profile.pb");
    ok = ok && upF(pb, "u_abs", c.pb.u_abs, 27.0f, Config::U_SET_MAX, err, changed, "profile.pb");
    ok = ok && upF(pb, "u_float", c.pb.u_float, 26.0f, 28.0f, err, changed, "profile.pb");
    ok = ok && upF(pb, "i_abs_end", c.pb.i_abs_end, 0.2f, 5.0f, err, changed, "profile.pb");
    ok = ok && upF(pb, "tc_v_per_c", c.pb.tc_v_per_c, -0.06f, 0.0f, err, changed, "profile.pb");
    ok = ok && upF(pb, "t_ref", c.pb.t_ref, 15, 35, err, changed, "profile.pb");
    ok = ok && upF(pb, "t_max", c.pb.t_max, 20, 60, err, changed, "profile.pb");
  }
  if (v["discharge"].is<JsonObjectConst>()) {
    ok = ok && upF(v["discharge"]["1"], "u_off", c.dis[0].u_off, 20, 28, err, changed, "discharge.1");
    ok = ok && upF(v["discharge"]["1"], "u_on", c.dis[0].u_on, 20, 29, err, changed, "discharge.1");
    ok = ok && upF(v["discharge"]["2"], "u_off", c.dis[1].u_off, 20, 28, err, changed, "discharge.2");
    ok = ok && upF(v["discharge"]["2"], "u_on", c.dis[1].u_on, 20, 29, err, changed, "discharge.2");
  }
  if (v["policy"].is<JsonObjectConst>()) {
    JsonObjectConst p = v["policy"];
    if (p["auto"].is<bool>()) { c.policy_auto = p["auto"]; changed += "policy.auto,"; }
    if (p["charge_order"].is<const char*>()) {
      const char* o = p["charge_order"];
      if (strcmp(o, "lowest_soc") && strcmp(o, "b1_first") && strcmp(o, "b2_first") && strcmp(o, "manual")) { err = "policy.charge_order"; ok = false; }
      else { strlcpy(c.policy_order, o, sizeof(c.policy_order)); changed += "policy.charge_order,"; }
    }
    if (p["rest_min"].is<int>()) { int r = p["rest_min"]; if (r < 0 || r > 120) { err = "policy.rest_min"; ok = false; } else { c.rest_min = r; changed += "policy.rest_min,"; } }
  }
  if (v["oled"]["timeout_s"].is<int>()) { int t = v["oled"]["timeout_s"]; if (t < 10 || t > 3600) { err = "oled.timeout_s"; ok = false; } else { c.oled_timeout_s = t; changed += "oled.timeout_s,"; } }
  if (v["limits"].is<JsonObjectConst>()) { err = "limits are read-only"; ok = false; }
  if (!ok) { c = backup; changed = ""; return false; }
  return cfgSave();
}
