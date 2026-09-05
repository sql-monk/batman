// batman — менеджер двох акумуляторів. Вимоги: docs/firmware.md
#include <Arduino.h>
#include <esp_task_wdt.h>
#include "version.h"
#include "pins.h"
#include "config.h"
#include "dps5015.h"
#include "measure.h"
#include "control.h"
#include "net.h"
#include "ui.h"

static void slowTask(void*) {
  esp_task_wdt_add(NULL);
  uint32_t lastSlow = 0;
  for (;;) {
    uint32_t now = millis();
    if (now - lastSlow >= 1000) { lastSlow = now; measureSlowTick(); }
    uiTick();
    esp_task_wdt_reset();
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}

static void ctrlTask(void*) {
  esp_task_wdt_add(NULL);
  TickType_t last = xTaskGetTickCount();
  for (;;) {
    controlTickOnce();
    esp_task_wdt_reset();
    vTaskDelayUntil(&last, pdMS_TO_TICKS(500));
  }
}

void setup() {
  controlBegin();                     // 1. виходи у безпечний стан — до всього
  Serial.begin(115200);
  delay(50);
  Serial.printf("\n[boot] batman fw %s\n", FW_VERSION);
  esp_task_wdt_config_t wdt = { .timeout_ms = 10000, .idle_core_mask = 0, .trigger_panic = true };
  esp_task_wdt_reconfigure(&wdt);     // 2. watchdog
  cfgLoad();                          // 3. NVS
  dpsBegin();                         // 4. шини й периферія
  measureBegin();                     // 5. датчики під живленням, перший блок
  uiBegin();
  controlAfterInit();                 // 6–7. DPS off, відновлення ключів, подія boot
  netBegin();                         // 8. Wi-Fi, HTTP, mDNS

  xTaskCreatePinnedToCore(measureTask, "acq", 4096, NULL, 3, NULL, 1);
  xTaskCreatePinnedToCore(ctrlTask, "ctrl", 8192, NULL, 2, NULL, 1);
  xTaskCreatePinnedToCore(slowTask, "slow", 4096, NULL, 1, NULL, 0);
  xTaskCreatePinnedToCore(netTask, "net", 8192, NULL, 1, NULL, 0);
}

void loop() {
  static uint32_t lastLog = 0;
  if (millis() - lastLog >= 3600000UL) {
    lastLog = millis();
    Serial.printf("[I] up %lus heap %u min %u state %s crc %lu\n", (unsigned long)(millis() / 1000),
                  ESP.getFreeHeap(), ESP.getMinFreeHeap(), stName(controlState()), (unsigned long)dpsRegs().crcErrors);
  }
  delay(1000);
}
