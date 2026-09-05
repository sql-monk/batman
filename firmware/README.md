# Прошивка ESP32

Вимоги — [docs/firmware.md](../docs/firmware.md); піни — [docs/connections.md](../docs/connections.md) і `batman/pins.h`.

## Збірка

**PlatformIO** (VS Code або `pio`): відкрити цю теку, `pio run -t upload`, монітор `pio device monitor`. Розділи `min_spiffs` (два слоти під OTA по 1,9 МБ).

**arduino-cli** (те саме, без PlatformIO):
```bash
arduino-cli compile --fqbn esp32:esp32:esp32 --board-options PartitionScheme=min_spiffs firmware/batman
```
```bash
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32 --board-options PartitionScheme=min_spiffs firmware/batman
```
Бібліотеки: ADS1X15 (RobTillaart), OneWire, DallasTemperature, U8g2, ArduinoJson 7 — `arduino-cli lib install …`. Ядро esp32 3.x.

## Файли

| Файл | Що |
|---|---|
| `batman.ino` | `setup()` у порядку безпечного старту, задачі FreeRTOS, watchdog |
| `pins.h` | розкладка пінів і номінали трактів |
| `state.h` | стани, знімок, коди попереджень |
| `config.*` | конфіг у NVS, JSON туди-сюди з межами |
| `dps5015.*` | Modbus RTU до DPS5015 (власний, 0x03/0x06/0x10, таймаут 200 мс) |
| `measure.*` | ADS1115 по колу, інтегрування, автонуль, калібрування, лічильники в NVS, DS18B20, ADC1 |
| `control.*` | стейт-машина, ключі mSW, реле K1/K2, FAULT, команди |
| `net.*` | Wi-Fi/AP, mDNS, UDP-пошук, HTTP-API, телеметрія з буфером, OTA, вбудована сторінка |
| `ui.*` | OLED-екрани й кнопка |

## Перший запуск

1. Прошити. Без збереженого Wi-Fi пристрій підіймає AP `batman-<id>` (пароль `batmanbat`), сторінка `http://192.168.4.1/` — ввести SSID, пароль і за бажанням URL приймача.
2. Після перезавантаження — `http://batman-<id>.local/` (або IP з роутера): стан, кнопки, `/status`, `/telemetry`, `/config`.
3. Сервіс знайде пристрій сам (mDNS/UDP) і надішле `POST /sink`.

## Що ще не зроблено в коді

- DS18B20 беруться за індексом (0 → T1, 1 → T2), не за адресою: при заміні датчика перевірити, який де.
- ArduinoOTA для розробки не ввімкнений — лише `POST /update`.
- NTP/годинник на OLED відсутні (протоколу вони не потрібні).
