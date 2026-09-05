"""Реєстр пристроїв, підключення (POST /sink), проксі команд і конфігу, контроль зв'язку."""
from __future__ import annotations
import json
import logging
import threading
import httpx
from . import db
from .config import CFG
from .notify import notify

log = logging.getLogger("devices")


def base_url(dev: dict | "db.sqlite3.Row") -> str:
    return f"http://{dev['ip']}:{dev['port'] or 80}"


def connect(dev_id: str, public_url: str | None = None) -> dict:
    dev = db.q1("SELECT * FROM device WHERE id=?", (dev_id,))
    if not dev or not dev["ip"]:
        return {"ok": False, "error": "unknown device or no ip"}
    url = (public_url or CFG.server.public_url).rstrip("/") + "/api/ingest"
    try:
        r = httpx.post(base_url(dev) + "/sink", json={"v": 1, "url": url, "interval_s": 2}, timeout=5)
        ok = r.status_code == 200
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    db.x("UPDATE device SET sink_ok=?, status=CASE WHEN ? THEN 'connected' ELSE status END WHERE id=?", (int(ok), ok, dev_id))
    return {"ok": ok, "status": r.status_code, "body": r.text[:200]}


def proxy(dev_id: str, path: str, method: str = "GET", body: dict | None = None, timeout: float = 8) -> tuple[int, dict | str]:
    dev = db.q1("SELECT * FROM device WHERE id=?", (dev_id,))
    if not dev or not dev["ip"]:
        return 404, {"ok": False, "error": "unknown device"}
    try:
        r = httpx.request(method, base_url(dev) + path, json=body, timeout=timeout)
        try:
            return r.status_code, r.json()
        except Exception:  # noqa: BLE001
            return r.status_code, r.text
    except Exception as e:  # noqa: BLE001
        return 502, {"ok": False, "error": str(e)}


def control(dev_id: str, body: dict, by: str = "web") -> tuple[int, dict | str]:
    code, res = proxy(dev_id, "/control", "POST", body)
    db.x("INSERT INTO event(device_id,t,event,data) VALUES(?,?,?,?)",
         (dev_id, db.now_ms(), "command", json.dumps({"cmd": body.get("cmd"), "args": body, "by": by, "result": code})))
    return code, res


def set_config(dev_id: str, body: dict) -> tuple[int, dict | str]:
    code, res = proxy(dev_id, "/config", "POST", body)
    if code == 200 and isinstance(res, dict):
        db.x("UPDATE device SET config_json=? WHERE id=?", (json.dumps(res), dev_id))
    return code, res


def watchdog(stop: threading.Event) -> None:
    """Раз на 10 с: хто мовчить довше 3×interval+5 с → gap no_data + offline; раз на 10 хв — перевірка sink."""
    tick = 0
    while not stop.is_set():
        now = db.now_ms()
        for d in db.q("SELECT * FROM device WHERE status IN ('connected','unclaimed')"):
            iv = 2
            try:
                iv = int(json.loads(d["config_json"] or "{}").get("sink", {}).get("interval_s") or 2)
            except Exception:  # noqa: BLE001
                pass
            if d["last_seen"] and now - d["last_seen"] > (3 * iv + 5) * 1000:
                g = db.q1("SELECT id, t_from FROM gap WHERE device_id=? AND kind='no_data' AND t_to IS NULL", (d["id"],))
                if not g:
                    db.x("INSERT INTO gap(device_id,t_from,kind) VALUES(?,?,'no_data')", (d["id"], d["last_seen"]))
                elif now - g["t_from"] > CFG.alerts.offline_min * 60_000:
                    notify("offline", d["id"], f"{d['id']}: немає телеметрії {(now - g['t_from']) // 60000} хв", once_per_s=3600)
        if tick % 60 == 0 and CFG.server.public_url:
            for d in db.q("SELECT * FROM device WHERE status='connected'"):
                code, st = proxy(d["id"], "/status", timeout=4)
                if code == 200 and isinstance(st, dict):
                    want = CFG.server.public_url.rstrip("/") + "/api/ingest"
                    if (st.get("sink") or {}).get("url") != want:
                        log.info("re-sink %s", d["id"])
                        connect(d["id"])
                    db.x("UPDATE device SET fw=? WHERE id=?", (st.get("fw"), d["id"]))
        tick += 1
        stop.wait(10)
