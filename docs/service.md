# Сервіс — вимоги

Кросплатформений сервіс збору й аналітики: Python 3.11+, FastAPI, SQLite, один процес. Windows зараз, Raspberry Pi 4 потім, Docker опційно. Протокол з пристроєм — protocol.md.

## Що робить

1. Знаходить пристрої (mDNS, UDP-broadcast, ручний IP), реєструє, каже їм, куди слати (`POST /sink`).
2. Приймає телеметрію й події, зберігає сирі записи, стежить за розривами.
3. Рахує агрегати: година / доба / цикл — А·год і Вт·год у/з кожного акумулятора, ефективність, час у станах, мін/макс.
4. Показує: стан, графіки, таблиці циклів, події; експорт CSV.
5. Пересилає команди й конфіг на пристрій.
6. Сповіщає про FAULT, втрату зв'язку, низький SoC.

## Структура

```
service/
  batman_service/
    main.py          FastAPI-застосунок, запуск uvicorn
    config.py        читання config.toml + змінні середовища
    db.py            SQLite (sqlite3 або SQLAlchemy Core), міграції в migrations/
    discovery.py     mDNS (zeroconf) + UDP + ручний список
    ingest.py        POST /api/ingest — приймання, валідація, запис
    aggregate.py     періодичні агрегати, детекція циклів
    devices.py       реєстр, проксі команд на пристрій
    notify.py        журнал, e-mail, Telegram
    web/             сторінки (Jinja2) + статика; графіки — uPlot або Chart.js, локально, без CDN
  migrations/        001_init.sql …
  config.toml.example
  deploy/            nssm-install.ps1, batman.service (systemd), Dockerfile
  tests/
  emulator/          device_emulator.py — фейковий пристрій: шле телеметрію, відповідає на REST
```

## БД (SQLite, WAL)

| Таблиця | Колонки (головне) | Примітка |
|---|---|---|
| `device` | `id` (text, PK, = `id` пристрою), `name`, `ip`, `port`, `fw`, `first_seen`, `last_seen`, `sink_ok`, `config_json` | |
| `boot` | `id`, `device_id`, `t_service`, `uptime0`, `reset_reason` | для перерахунку `uptime → час` |
| `sample` | `id`, `device_id`, `t` (unix ms, час сервісу), `seq`, `uptime`, `state`, `b1_u`, `b1_i`, `b1_t`, `b1_soc`, `b1_sw`, `b1_ah_in`, `b1_ah_out`, `b1_wh_in`, `b1_wh_out`, `b2_*` (те саме), `load_u`, `load_i`, `dps_uin`, `dps_uout`, `dps_iout`, `dps_uset`, `dps_iset`, `dps_on`, `dps_cc`, `dps_prot`, `dps_k`, `rssi`, `warn` (text), `raw` (json) | індекс `(device_id, t)`; `raw` — повний JSON на випадок нових полів |
| `event` | `id`, `device_id`, `t`, `seq`, `uptime`, `event`, `from_state`, `to_state`, `reason`, `data` (json) | індекс `(device_id, t)` |
| `gap` | `device_id`, `t_from`, `t_to`, `seq_from`, `seq_to`, `kind` (`no_data` / `seq_gap` / `reboot`) | розриви |
| `agg_hour`, `agg_day` | `device_id`, `bat` (1/2), `t_start`, `ah_in`, `ah_out`, `wh_in`, `wh_out`, `u_min`, `u_max`, `u_avg`, `i_min`, `i_max`, `t_min`, `t_max`, `soc_min`, `soc_max`, `s_charge`, `s_float`, `s_idle`, `s_fault` (секунди в станах), `samples`, `gaps` | |
| `cycle` | `id`, `device_id`, `bat`, `t_start`, `t_end`, `ah_in`, `ah_out`, `wh_in`, `wh_out`, `eff` (= `ah_out_prev / ah_in`), `duration_s`, `end_reason`, `u_start`, `i_tail` | з подій `state` + `cycle_complete` |
| `notification` | `id`, `t`, `device_id`, `kind`, `text`, `sent` | |

Ретенція: сирі `sample` старші за `retention.raw_days` (типово 90) проріджуються до 1 запису на хвилину; старші за `retention.min_days` (365) — видаляються; агрегати живуть вічно. `VACUUM` раз на тиждень уночі.

## Приймання

`POST /api/ingest` — тіло: масив повідомлень (protocol.md). На кожне:
- валідація `v`, `id`, `type`; невідомий `id` → авто-реєстрація зі статусом `unclaimed`;
- `t = now()`; при `event: boot` — новий запис у `boot`; для повідомлень з буфера (прийшли пачкою) `t` рахується як `now − (uptime_last − uptime_msg)`;
- `seq` порівнюється з попереднім: пропуск → `gap kind=seq_gap`; `uptime` менший за попередній без `boot` → `gap kind=reboot`;
- запис у `sample`/`event`, оновлення `device.last_seen`.
Відповідь `200 {"ok":true,"accepted":N}`. Без відповіді пристрій буферизує — тому обробка має бути швидкою (< 50 мс), агрегати рахуються окремо.

Контроль зв'язку: фонова задача раз на 10 с — пристрій без телеметрії довше `3 × interval_s + 5` с → `gap kind=no_data` + сповіщення `offline`; повернення → закриття gap.

## Пошук і реєстрація

- `zeroconf` слухає `_batman._tcp`; UDP-broadcast `BATMAN?` на 47474 раз на 60 с (і по кнопці «Знайти»); ручне додавання за IP.
- Знайдений пристрій → `device` зі статусом `discovered`; користувач натискає «Підключити» → сервіс робить `POST /sink` зі своєю адресою (`public_url` з конфігу, бо адресу приймача пристрій має бачити зі свого боку мережі) і `interval_s`; успіх → `sink_ok = 1`.
- Раз на 10 хв сервіс перевіряє `GET /status` пристрою: якщо `sink` там не наш — повторює `POST /sink` (пристрій міг перезавантажитись без NVS або хтось перехопив).

## Агрегати

Задача раз на хвилину: для кожного пристрою й гілки добудовує `agg_hour` для завершених годин (і поточну — з позначкою `partial`), раз на добу — `agg_day`. Джерело — сирі `sample`: інтегрування `bX_i` трапеціями по `t` (а не різниця лічильників пристрою — щоб розриви й ресети не псували; лічильники пристрою — для звірки, розбіжність > 3 % → попередження в журнал). Час у станах — за `state` у семплах.

Цикли: від події `state → CHG_Bx_*` (старт) до `cycle_complete` або `state → IDLE` з іншої причини (`end_reason`). `eff` — А·год, віддані з моменту попереднього «100 %», поділені на А·год, прийняті в цьому циклі.

## Сторінки

| Шлях | Що |
|---|---|
| `/` | усі пристрої: стан, U/I/SoC обох гілок, DPS, останнє повідомлення, попередження; автооновлення раз на 2 с (SSE `/api/stream`) |
| `/d/{id}` | пристрій: живі графіки за останні 1 год / 24 год / 7 діб — U, I, SoC, T обох гілок, U/I навантаження, DPS UIN/UOUT/IOUT; смуга станів; події |
| `/d/{id}/cycles` | таблиця циклів з фільтрами, ефективність, тривалість; клік → графік циклу |
| `/d/{id}/events` | події й попередження, фільтр за типом |
| `/d/{id}/control` | старт/стоп заряду, ключі, скидання FAULT, калібрування (з підказкою, що для цього треба), конфіг (форма за `GET /config`), OTA (завантажити `.bin`) |
| `/d/{id}/export` | CSV: семпли за період (з проріджуванням), агрегати, цикли, події |
| `/settings` | сервіс: `public_url`, ретенція, сповіщення, ручне додавання пристрою |

Мінімум JS, без збірки фронтенду: Jinja2 + uPlot (одна статика). Графіки — з `agg_hour` для довгих періодів, із сирих — для ≤ 24 год.

## Команди

`POST /api/d/{id}/control` → проксі на `POST http://<ip>/control` з тим самим тілом; відповідь пристрою повертається як є; кожна команда — запис у `event` з `event=command`, `data={cmd, by, result}`. Те саме для `/config`.

## Сповіщення

Канали: журнал (завжди), e-mail (SMTP), Telegram (bot token + chat id). Події: `fault` (негайно), `offline` довше 5 хв, `soc < soc_alert` (типово 20 %), `warn` новий код (раз на добу на код), `cycle_complete` (опційно). Антидребезг: одне сповіщення на подію, «відбій» окремо.

## Конфіг сервісу (`config.toml`)

```toml
[server]      host = "0.0.0.0"   port = 8000   public_url = "http://192.168.1.10:8000"
[db]          path = "data/batman.db"
[discovery]   mdns = true   udp = true   udp_interval_s = 60
[retention]   raw_days = 90   min_days = 365
[alerts]      soc_alert = 20   offline_min = 5
[alerts.telegram]  enabled = false   token = ""   chat_id = ""
[alerts.email]     enabled = false   smtp = ""   from = ""   to = ""
```

## Розгортання

- **Windows:** `deploy/nssm-install.ps1` — створює службу `batman` (`python -m batman_service`), лог у `logs/`; альтернатива — Task Scheduler при вході.
- **Raspberry Pi 4:** `deploy/batman.service` (systemd, `Restart=always`, `User=batman`), venv у `/opt/batman`.
- **Docker:** `Dockerfile` + том для `data/`; `network_mode: host` — інакше mDNS/UDP не працюють.
- Оновлення: `git pull` + міграції при старті (номер схеми в таблиці `meta`).

## Емулятор

`emulator/device_emulator.py --id test01 --sink http://localhost:8000/api/ingest` — імітує пристрій за protocol.md: відповідає на UDP і REST, шле телеметрію з правдоподібними кривими заряду/розряду, реагує на команди. Ним сервіс доводиться до готового стану без заліза (кроки 5.1–5.5 плану).

## Тести

`pytest`: валідація ingest (порядок, буфер, пропуски seq, ресет), агрегати на синтетичних даних (відома площа під кривою), детекція циклів, міграції з порожньої БД, емулятор ↔ сервіс end-to-end.
