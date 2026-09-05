// Конфіг у NVS. Ключі й типові значення — docs/firmware.md, формат JSON — docs/protocol.md.
#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

struct ProfileLi { float i_cc = 10.0f, u_cv = 28.80f, i_tail = 2.5f, t_min = 0.0f, t_max = 45.0f; };
struct ProfilePb { float i_bulk = 10.0f, u_abs = 28.80f, u_float = 27.40f, i_abs_end = 1.3f,
                   tc_v_per_c = -0.036f, t_ref = 25.0f, t_max = 45.0f; };
struct Discharge { float u_off, u_on; };

struct Config {
  char wifi_ssid[33] = "";
  char wifi_pass[65] = "";
  char sink_url[128] = "";
  char sink_token[64] = "";
  uint16_t sink_interval_s = 2;
  float c_nom[2] = {50.0f, 65.0f};
  ProfileLi li;
  ProfilePb pb;
  Discharge dis[2] = {{24.0f, 25.2f}, {23.0f, 24.6f}};
  bool policy_auto = false;
  char policy_order[12] = "lowest_soc";
  uint16_t rest_min = 10;
  uint16_t oled_timeout_s = 120;
  // Стеля заліза — не з API
  static constexpr float I_SET_MAX = 12.0f;
  static constexpr float U_SET_MAX = 29.8f;
};

Config& cfg();
void cfgLoad();
bool cfgSave();
void cfgToJson(JsonObject o);
// Часткове оновлення; повертає false і текст помилки при виході за межі
bool cfgFromJson(JsonVariantConst v, String& err, String& changed);
String deviceId();   // останні 3 байти MAC, hex
