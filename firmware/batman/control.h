// Стейт-машина, ключі, реле, FAULT — docs/firmware.md
#pragma once
#include "state.h"
#include <ArduinoJson.h>

void controlBegin();          // безпечний старт виходів — викликати ПЕРШИМ у setup()
void controlAfterInit();      // після NVS/DPS: відновлення стану, перший блок
void controlTickOnce();       // один тік 500 мс (викликає задача ctrl у batman.ino)
void controlFill(Snapshot& s);
St controlState();
// Команда з REST/кнопки. Повертає HTTP-код (200/400/409/423), err — текст при помилці
int controlCmd(const char* cmd, JsonVariantConst a, String& err);
void snapshotGet(Snapshot& s);   // повний знімок (measure + control + net)
