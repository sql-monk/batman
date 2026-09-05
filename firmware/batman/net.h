// Wi-Fi, mDNS/UDP-пошук, HTTP-сервер, телеметрія на sink, OTA — docs/protocol.md
#pragma once
#include <Arduino.h>
#include "state.h"

void netBegin();
void netTask(void* arg);
int netRssi();
bool netSinkOk();
uint32_t netNextSeq();
