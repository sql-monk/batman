# Сервіс збору й аналітики

Вимоги — [docs/service.md](../docs/service.md), протокол — [docs/protocol.md](../docs/protocol.md). Python 3.11+, FastAPI, SQLite.

## Запуск

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
```
```bash
cp config.toml.example config.toml   # виставити public_url — адресу, за якою пристрої бачать цей комп'ютер
```
```bash
.venv/Scripts/python -m batman_service
```
Відкрити `http://localhost:8000/`. Пристрої знаходяться через mDNS і UDP («Знайти»), або додаються за IP у налаштуваннях; кнопка «Підключити» відправляє пристрою `POST /sink`.

## Без заліза — емулятор

У другому терміналі:
```bash
.venv/Scripts/python emulator/device_emulator.py --id emu001 --port 8081 --sink http://localhost:8000/api/ingest --fast 120
```
Емулятор відповідає на UDP-пошук і REST, шле телеметрію, заряджає/розряджає за профілями (`--fast 120` — 2 хвилини = 4 години моделі). У сервісі: «Знайти» → «Підключити» (або він уже шле, бо `--sink` заданий) → графіки, цикли, події, керування.

## Тести

```bash
.venv/Scripts/python -m pytest -q tests
```

## Структура

| | |
|---|---|
| `batman_service/main.py` | FastAPI: сторінки, API, SSE, фонові потоки |
| `ingest.py` | `POST /api/ingest`: валідація, час, розриви, ресети, запис, сповіщення |
| `aggregate.py` | година/доба (інтегрування сирих), цикли, ретенція |
| `discovery.py` | mDNS + UDP-broadcast + ручний список |
| `devices.py` | підключення (`/sink`), проксі команд і конфігу, контроль зв'язку |
| `notify.py` | журнал, Telegram, e-mail |
| `web/` | Jinja2-шаблони, uPlot (локально, без CDN) |
| `migrations/` | схема БД |
| `emulator/` | фейковий пристрій |
| `deploy/` | NSSM (Windows), systemd (RPi), Dockerfile |

## Розгортання

- **Windows:** `powershell -ExecutionPolicy Bypass -File deploy\nssm-install.ps1` (потрібен `nssm` у PATH).
- **Raspberry Pi 4:** клон у `/opt/batman`, venv, `config.toml`, `sudo cp deploy/batman.service /etc/systemd/system/ && sudo systemctl enable --now batman`.
- **Docker:** `deploy/Dockerfile`, обов'язково `--network host`.

## API сервісу (для скриптів)

`GET /api/devices` · `POST /api/discover` · `POST /api/devices/manual {ip,port}` · `POST /api/d/{id}/connect` · `POST /api/d/{id}/control {cmd,…}` · `GET|POST /api/d/{id}/config` · `GET /api/d/{id}/series?hours=` · `GET /api/d/{id}/events` · `GET /api/d/{id}/cycles` · `GET /api/d/{id}/agg?res=day|hour` · `GET /api/d/{id}/export.csv?what=samples|agg_hour|agg_day|cycles|events` · `GET /api/stream` (SSE) · `GET /health`.
