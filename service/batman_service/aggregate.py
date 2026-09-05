"""Агрегати година/доба з сирих семплів (інтегрування трапеціями по t), цикли з подій, ретенція."""
from __future__ import annotations
import json
import logging
import time
from . import db

log = logging.getLogger("aggregate")
HOUR = 3600_000
DAY = 86400_000

STATE_CLASS = {
    "CHG_B1_CC": "charge", "CHG_B1_CV": "charge", "CHG_B2_BULK": "charge", "CHG_B2_ABS": "charge",
    "CHG_B2_FLOAT": "float", "FAULT": "fault",
}


def _agg_window(dev: str, bat: int, t0: int, t1: int) -> dict | None:
    rows = db.q(f"SELECT t, b{bat}_u AS u, b{bat}_i AS i, b{bat}_t AS tt, b{bat}_soc AS soc, state "
                f"FROM sample WHERE device_id=? AND t>=? AND t<? ORDER BY t", (dev, t0, t1))
    if not rows:
        return None
    ah_in = ah_out = wh_in = wh_out = 0.0
    s = {"charge": 0, "float": 0, "idle": 0, "fault": 0}
    us, is_, ts, socs = [], [], [], []
    prev = None
    for r in rows:
        if r["u"] is not None:
            us.append(r["u"])
        if r["i"] is not None:
            is_.append(r["i"])
        if r["tt"] is not None:
            ts.append(r["tt"])
        if r["soc"] is not None:
            socs.append(r["soc"])
        if prev is not None and r["i"] is not None and prev["i"] is not None:
            dt = (r["t"] - prev["t"]) / 1000
            if 0 < dt <= 60:   # розрив довший за хвилину не інтегруємо
                q = (r["i"] + prev["i"]) / 2 * dt
                u = ((r["u"] or 0) + (prev["u"] or 0)) / 2
                if q > 0:
                    ah_in += q / 3600
                    wh_in += q * u / 3600
                else:
                    ah_out -= q / 3600
                    wh_out -= q * u / 3600
                cls = STATE_CLASS.get(prev["state"] or "", "idle")
                s[cls] += int(dt)
        prev = r
    gaps = db.q1("SELECT COUNT(*) AS n FROM gap WHERE device_id=? AND t_from<? AND (t_to IS NULL OR t_to>?)", (dev, t1, t0))["n"]
    return dict(ah_in=ah_in, ah_out=ah_out, wh_in=wh_in, wh_out=wh_out,
                u_min=min(us) if us else None, u_max=max(us) if us else None, u_avg=sum(us) / len(us) if us else None,
                i_min=min(is_) if is_ else None, i_max=max(is_) if is_ else None,
                t_min=min(ts) if ts else None, t_max=max(ts) if ts else None,
                soc_min=min(socs) if socs else None, soc_max=max(socs) if socs else None,
                s_charge=s["charge"], s_float=s["float"], s_idle=s["idle"], s_fault=s["fault"],
                samples=len(rows), gaps=gaps)


def _write(table: str, dev: str, bat: int, t0: int, a: dict, partial: int) -> None:
    cols = ["device_id", "bat", "t_start"] + list(a.keys()) + ["partial"]
    vals = [dev, bat, t0] + list(a.values()) + [partial]
    db.x(f"INSERT OR REPLACE INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(vals))})", vals)


def run_once() -> None:
    """Добудувати agg_hour/agg_day для годин і діб, у яких є семпли й ще немає повного агрегату."""
    now = db.now_ms()
    for d in db.q("SELECT id FROM device"):
        dev = d["id"]
        for table, size in (("agg_hour", HOUR), ("agg_day", DAY)):
            last = db.q1(f"SELECT MAX(t_start) AS t FROM {table} WHERE device_id=? AND partial=0", (dev,))["t"]
            t_from = (last + size) if last else 0
            buckets = db.q("SELECT DISTINCT (t / ?) AS b FROM sample WHERE device_id=? AND t>=? ORDER BY b", (size, dev, t_from))
            for row in buckets:
                t0 = row["b"] * size
                partial = 1 if t0 + size > now else 0
                for bat in (1, 2):
                    a = _agg_window(dev, bat, t0, min(t0 + size, now))
                    if a:
                        _write(table, dev, bat, t0, a, partial)


# ---- цикли ----
def on_state_event(dev: str, t: int, m: dict) -> None:
    to, frm = m.get("to") or "", m.get("from") or ""
    bat = 1 if "B1" in to else 2 if "B2" in to else 0
    if bat and to.startswith("CHG") and not frm.startswith("CHG"):
        open_ = db.q1("SELECT id FROM cycle WHERE device_id=? AND bat=? AND t_end IS NULL", (dev, bat))
        if not open_:
            u = db.q1(f"SELECT b{bat}_u AS u FROM sample WHERE device_id=? ORDER BY t DESC LIMIT 1", (dev,))
            db.x("INSERT INTO cycle(device_id,bat,t_start,u_start) VALUES(?,?,?,?)", (dev, bat, t, u["u"] if u else None))
    bat_from = 1 if "B1" in frm else 2 if "B2" in frm else 0
    if bat_from and frm.startswith("CHG") and not to.startswith("CHG"):
        c = db.q1("SELECT id, t_start FROM cycle WHERE device_id=? AND bat=? AND t_end IS NULL", (dev, bat_from))
        if c:
            db.x("UPDATE cycle SET t_end=?, duration_s=?, end_reason=COALESCE(end_reason,?) WHERE id=?",
                 (t, (t - c["t_start"]) // 1000, m.get("reason"), c["id"]))


def on_cycle_complete(dev: str, t: int, data: dict) -> None:
    bat = int(data.get("bat") or 0)
    c = db.q1("SELECT id, t_start FROM cycle WHERE device_id=? AND bat=? AND t_end IS NULL", (dev, bat))
    if not c:
        cid = db.x("INSERT INTO cycle(device_id,bat,t_start) VALUES(?,?,?)", (dev, bat, t))
        t_start = t
    else:
        cid, t_start = c["id"], c["t_start"]
    prev = db.q1("SELECT ah_out FROM cycle WHERE device_id=? AND bat=? AND id<? ORDER BY id DESC LIMIT 1", (dev, bat, cid))
    ah_in = float(data.get("ah_in") or 0)
    eff = (float(prev["ah_out"]) / ah_in) if prev and prev["ah_out"] and ah_in > 0 else None
    db.x("UPDATE cycle SET ah_in=?, ah_out=?, wh_in=?, wh_out=?, eff=?, end_reason='complete', i_tail=? WHERE id=?",
         (ah_in, data.get("ah_out"), data.get("wh_in"), data.get("wh_out"), eff, data.get("i_tail"), cid))


# ---- ретенція ----
def retention() -> None:
    from .config import CFG
    now = db.now_ms()
    lim_raw = now - CFG.retention.raw_days * DAY
    lim_min = now - CFG.retention.min_days * DAY
    db.x("DELETE FROM sample WHERE t<?", (lim_min,))
    # проріджування до 1 на хвилину: лишаємо запис із найменшим id у кожній хвилині
    db.x("DELETE FROM sample WHERE t<? AND id NOT IN (SELECT MIN(id) FROM sample WHERE t<? GROUP BY device_id, t/60000)", (lim_raw, lim_raw))


def loop(stop) -> None:
    last_ret = 0
    while not stop.is_set():
        try:
            run_once()
            if time.time() - last_ret > 6 * 3600:
                retention()
                last_ret = time.time()
        except Exception as e:  # noqa: BLE001
            log.exception("aggregate: %s", e)
        stop.wait(60)
