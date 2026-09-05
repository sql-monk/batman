# Протокол пристрій ↔ сервіс

Пристрій — джерело даних, сервіс — пам'ять. Пристрій **сам** шле телеметрію на адресу, яку йому повідомив сервіс; сервіс знаходить пристрій у мережі. Усе — JSON по HTTP, без TLS (локальна мережа).

Версія протоколу: `v: 1`. Поле `v` є в кожному повідомленні; несумісні зміни підіймають номер, сумісні (нові поля) — ні. Невідомі поля ігноруються обома сторонами.

## Пошук пристрою

1. **mDNS:** пристрій анонсує `batman-<id>.local`, сервіс `_batman._tcp`, порт 80, TXT: `id=<id>`, `fw=<версія>`, `v=1`. `<id>` — останні 3 байти MAC, hex, наприклад `batman-a1b2c3`.
2. **UDP-broadcast (резерв):** сервіс шле `BATMAN?` на порт **47474** broadcast; пристрій відповідає на адресу відправника `{"v":1,"id":"a1b2c3","ip":"192.168.1.50","port":80,"fw":"0.3.1"}`.
3. **Вручну:** IP у сервісі.

## Підключення приймача

`POST http://<пристрій>/sink`
```json
{"v":1, "url":"http://192.168.1.10:8000/api/ingest", "interval_s":2, "token":"опційно"}
```
Відповідь `200 {"ok":true}`. Пристрій зберігає в NVS і починає слати. `interval_s` — 1…60. `DELETE /sink` — перестати. Якщо `token` заданий — пристрій додає заголовок `Authorization: Bearer <token>`.

## Потік від пристрою

Один `POST <url>` на кожне повідомлення. Тіло — **масив** повідомлень (звичайно з одним елементом; після відновлення зв'язку — усе з буфера, до 100 штук).

### Телеметрія (`type: "telemetry"`, кожні `interval_s`)

```json
{
  "v": 1, "type": "telemetry", "id": "a1b2c3", "seq": 18234, "uptime": 91234,
  "state": "CHG_B1_CV",
  "b1": {"u": 28.61, "i": 3.42, "t": 24.5, "soc": 91.3, "sw": "off",
         "ah_in": 12.418, "ah_out": 0.000, "wh_in": 347.2, "wh_out": 0.0,
         "ah_in_tot": 1204.3, "ah_out_tot": 1188.7, "cycles": 41},
  "b2": {"u": 26.02, "i": -4.31, "t": 23.0, "soc": 62.0, "sw": "on",
         "ah_in": 0.000, "ah_out": 21.750, "wh_in": 0.0, "wh_out": 560.1,
         "ah_in_tot": 2210.0, "ah_out_tot": 2190.5, "cycles": 77},
  "load": {"u": 25.71, "i": 4.28},
  "dps": {"ok": true, "uin": 33.05, "uout": 29.10, "iout": 3.50, "uset": 29.10, "iset": 10.00,
          "on": true, "cc": false, "prot": 0, "k": 1},
  "fault": null,
  "wifi": {"rssi": -58},
  "warn": ["sensor_mismatch"]
}
```

| Поле | Що |
|---|---|
| `seq` | наскрізний лічильник повідомлень з моменту старту; розриви = втрати |
| `uptime` | секунди з моменту старту; час у записах ставить **сервіс** при отриманні |
| `state` | стан стейт-машини (firmware.md) |
| `bX.i` | А, **+ заряд / − розряд** |
| `bX.sw` | `off` / `on` / `forced` (повзунок mSW у ON, керування неможливе) |
| `bX.ah_*`, `wh_*` | за поточний цикл; `*_tot` — наростаючим підсумком |
| `bX.soc` | %, або `null`, якщо не синхронізований понад 7 діб |
| `dps.k` | 0 — реле розімкнені, 1 / 2 — замкнене K1 / K2 |
| `dps.prot` | 0 норма, 1 OVP, 2 OCP, 3 OPP |
| `fault` | `null` або `{"code":"OC_LATCH","since":91100,"detail":"..."}` |
| `warn` | масив активних попереджень (коди нижче), може бути порожнім |

### Події (`type: "event"`, негайно)

```json
{"v":1,"type":"event","id":"a1b2c3","seq":18235,"uptime":91240,
 "event":"state","from":"CHG_B1_CV","to":"IDLE","reason":"tail_current",
 "data":{"bat":1,"ah_in":12.418,"wh_in":347.2,"duration_s":5412}}
```

| `event` | `reason` / `data` |
|---|---|
| `boot` | `{"fw":..., "reset_reason":..., "restored":true}` |
| `state` | `from`, `to`, `reason` (`user`, `tail_current`, `t_low`, `u_low`, `no_input`, `fault`, `policy`, `timeout`) |
| `cycle_complete` | `bat`, підсумки циклу |
| `switch` | `{"bat":1,"sw":"on","by":"user\|policy\|fault"}` |
| `fault` | `{"code":..., "detail":...}`; `fault_cleared` |
| `warn` | `{"code":..., "on":true\|false}` |
| `calibration` | `{"ch":..., "zero":..., "gain":...}` |
| `config` | `{"changed":["profile.pb.u_float"]}` |
| `dps` | `{"what":"protect","prot":2}` або `{"what":"timeout"}` |

Коди попереджень: `sensor_mismatch`, `u_mismatch`, `sum_mismatch`, `zero_drift`, `sw_forced`, `dps_crc`, `t_missing`, `soc_stale`, `nvs_write_fail`, `buffer_drop`.
Коди відмов: `OC_LATCH`, `DPS_TIMEOUT`, `DPS_PROTECT`, `DPS_STATE_MISMATCH`, `RELAY_STUCK`, `T_OVER`.

### Буфер

Якщо `POST` не вдався — повідомлення в кільцевий буфер в RAM: до 300 телеметрій (≈ 10 хв при 2 с) і до 100 подій, події не витісняються телеметрією. Повторна спроба — кожні 5 с; після успіху буфер зливається пачками по 100. Переповнення → попередження `buffer_drop` з кількістю втрачених.

## REST-API пристрою

| Метод | Шлях | Що |
|---|---|---|
| GET | `/status` | коротко: `id`, `fw`, `uptime`, `state`, `fault`, `sink`, `wifi`, `heap` |
| GET | `/telemetry` | одна телеметрія (як у потоці) |
| GET | `/events?since=<seq>` | останні події з RAM-журналу (до 100) |
| POST / DELETE | `/sink` | приймач (вище) |
| GET / POST | `/config` | повний конфіг / часткове оновлення (`{"profile":{"pb":{"u_float":27.4}}}`); відповідь — повний конфіг після змін |
| POST | `/control` | команда (нижче) |
| GET | `/calibration` | нулі й масштаби |
| POST | `/update` | OTA: multipart `.bin`; відповідь після перевірки образу, ресет через 2 с |
| GET | `/` | вбудована сторінка: стан, лічильники, Wi-Fi/сервіс, кнопки старт/стоп |

Команди `POST /control` — `{"cmd": "...", ...}`:

| `cmd` | Параметри | Що |
|---|---|---|
| `charge_start` | `bat: 1\|2` | почати заряд гілки (якщо стан дозволяє) |
| `charge_stop` | — | зупинити |
| `switch` | `bat`, `on: true\|false` | ключ гілки |
| `fault_clear` | — | скинути FAULT після усунення причини |
| `calibrate_zero` | `ch: 1\|2\|3` | ручний нуль (запобіжник знятий) |
| `calibrate_gain` | `ch`, `i_ref` | масштаб струму |
| `calibrate_ugain` | `ch: 1\|2\|load`, `u_ref` | масштаб напруги |
| `soc_set` | `bat`, `soc` | примусово задати SoC |
| `counters_reset` | `bat`, `what: "cycle"\|"total"` | обнулити лічильники |
| `reboot` | — | |

Відповідь: `200 {"ok":true}` або `4xx {"ok":false,"error":"текст"}`. Помилки: `400` формат, `409` стан не дозволяє (`"charging other battery"`), `423` FAULT активний.

## Конфіг (`GET /config`)

```json
{"v":1,
 "wifi":{"ssid":"…","hostname":"batman-a1b2c3"},
 "sink":{"url":"…","interval_s":2},
 "bat":{"1":{"chem":"lifepo4","c_nom":50.0},"2":{"chem":"pb","c_nom":65.0}},
 "profile":{"lifepo4":{"i_cc":10.0,"u_cv":28.80,"i_tail":2.5,"t_min":0.0,"t_max":45.0},
            "pb":{"i_bulk":10.0,"u_abs":28.80,"u_float":27.40,"i_abs_end":1.3,
                  "tc_v_per_c":-0.036,"t_ref":25.0,"t_max":45.0}},
 "discharge":{"1":{"u_off":24.0,"u_on":25.2},"2":{"u_off":23.0,"u_on":24.6}},
 "policy":{"charge_order":"lowest_soc","auto":true,"rest_min":10},
 "limits":{"i_set_max":12.0,"u_set_max":29.8},
 "oled":{"timeout_s":120}}
```

`limits` читаються, але **не змінюються** через API — це стеля заліза (concept.md).

## Часи й версії

- Пристрій не має годинника: усі мітки — `uptime` + `seq`; сервіс переводить у свій час при отриманні й запам'ятовує `boot` для перерахунку.
- NTP на пристрої — лише для журналу на OLED, у протокол не входить.
- `fw` — semver; сервіс показує, якщо у двох пристроїв різні мажорні версії протоколу.
