"""POST /api/ingest — приймання телеметрії й подій (docs/protocol.md), розриви, ресети."""
from __future__ import annotations
import json
from fastapi import APIRouter, Request
from . import db
from .notify import notify

router = APIRouter()

_last: dict[str, dict] = {}   # device_id -> {seq, uptime, t}


def _dev_upsert(dev_id: str, fw: str | None, ip: str | None, t: int) -> None:
    row = db.q1("SELECT id FROM device WHERE id=?", (dev_id,))
    if row is None:
        db.x("INSERT INTO device(id,name,ip,fw,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?)",
             (dev_id, "batman-" + dev_id, ip, fw, "unclaimed", t, t))
    else:
        db.x("UPDATE device SET last_seen=?, ip=COALESCE(?,ip), fw=COALESCE(?,fw) WHERE id=?", (t, ip, fw, dev_id))


def _num(v):
    return None if v is None else float(v)


def store_message(m: dict, t_recv: int, ip: str | None = None) -> str:
    """Записати одне повідомлення. Повертає тип або 'skip'."""
    if m.get("v") != 1 or "id" not in m or "type" not in m:
        return "skip"
    dev = str(m["id"])
    typ = m["type"]
    seq = int(m.get("seq") or 0)
    up = int(m.get("uptime") or 0)
    last = _last.get(dev)
    # Час: повідомлення з буфера прийшли пачкою — беремо зсув від останнього uptime
    t = t_recv
    if last and up < last["uptime_batch_max"]:
        t = t_recv - (last["uptime_batch_max"] - up) * 1000
    fw = m.get("data", {}).get("fw") if typ == "event" and m.get("event") == "boot" else None
    _dev_upsert(dev, fw, ip, t)

    # Ресет / пропуски
    if typ == "event" and m.get("event") == "boot":
        db.x("INSERT INTO boot(device_id,t_service,uptime0,reset_reason) VALUES(?,?,?,?)",
             (dev, t, up, (m.get("data") or {}).get("reset_reason")))
        if last:
            db.x("INSERT INTO gap(device_id,t_from,t_to,seq_from,seq_to,kind) VALUES(?,?,?,?,?,?)",
                 (dev, last["t"], t, last["seq"], seq, "reboot"))
        _last[dev] = {"seq": seq, "uptime": up, "t": t, "uptime_batch_max": up}
    elif last:
        if up + 5 < last["uptime"] and seq < last["seq"]:
            db.x("INSERT INTO gap(device_id,t_from,t_to,seq_from,seq_to,kind) VALUES(?,?,?,?,?,?)",
                 (dev, last["t"], t, last["seq"], seq, "reboot"))
        elif seq > last["seq"] + 1:
            db.x("INSERT INTO gap(device_id,t_from,t_to,seq_from,seq_to,kind) VALUES(?,?,?,?,?,?)",
                 (dev, last["t"], t, last["seq"], seq, "seq_gap"))
        _last[dev] = {"seq": max(seq, last["seq"]), "uptime": max(up, last["uptime"]), "t": max(t, last["t"]),
                      "uptime_batch_max": max(up, last["uptime_batch_max"])}
    else:
        _last[dev] = {"seq": seq, "uptime": up, "t": t, "uptime_batch_max": up}
    # Закрити відкритий розрив no_data
    g = db.q1("SELECT id FROM gap WHERE device_id=? AND kind='no_data' AND t_to IS NULL", (dev,))
    if g:
        db.x("UPDATE gap SET t_to=? WHERE id=?", (t, g["id"]))
        notify("online", dev, f"{dev}: зв'язок відновлено")

    if typ == "telemetry":
        b1, b2 = m.get("b1") or {}, m.get("b2") or {}
        ld, dp = m.get("load") or {}, m.get("dps") or {}
        db.x(
            "INSERT INTO sample(device_id,t,seq,uptime,state,"
            "b1_u,b1_i,b1_t,b1_soc,b1_sw,b1_ah_in,b1_ah_out,b1_wh_in,b1_wh_out,"
            "b2_u,b2_i,b2_t,b2_soc,b2_sw,b2_ah_in,b2_ah_out,b2_wh_in,b2_wh_out,"
            "load_u,load_i,dps_uin,dps_uout,dps_iout,dps_uset,dps_iset,dps_on,dps_cc,dps_prot,dps_k,rssi,warn,raw)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dev, t, seq, up, m.get("state"),
             _num(b1.get("u")), _num(b1.get("i")), _num(b1.get("t")), _num(b1.get("soc")), b1.get("sw"),
             _num(b1.get("ah_in")), _num(b1.get("ah_out")), _num(b1.get("wh_in")), _num(b1.get("wh_out")),
             _num(b2.get("u")), _num(b2.get("i")), _num(b2.get("t")), _num(b2.get("soc")), b2.get("sw"),
             _num(b2.get("ah_in")), _num(b2.get("ah_out")), _num(b2.get("wh_in")), _num(b2.get("wh_out")),
             _num(ld.get("u")), _num(ld.get("i")),
             _num(dp.get("uin")), _num(dp.get("uout")), _num(dp.get("iout")), _num(dp.get("uset")), _num(dp.get("iset")),
             int(bool(dp.get("on"))), int(bool(dp.get("cc"))), dp.get("prot"), dp.get("k"),
             (m.get("wifi") or {}).get("rssi"), ",".join(m.get("warn") or []), json.dumps(m, separators=(",", ":"))))
        # низький SoC
        for b in (1, 2):
            soc = (m.get(f"b{b}") or {}).get("soc")
            if soc is not None and soc < _soc_alert():
                notify(f"soc_low_{b}", dev, f"{dev}: SoC B{b} = {soc:.0f} %", once_per_s=3600)
        return "telemetry"

    if typ == "event":
        ev = m.get("event") or "?"
        db.x("INSERT INTO event(device_id,t,seq,uptime,event,from_state,to_state,reason,data) VALUES(?,?,?,?,?,?,?,?,?)",
             (dev, t, seq, up, ev, m.get("from"), m.get("to"), m.get("reason"),
              json.dumps(m.get("data"), separators=(",", ":")) if m.get("data") is not None else None))
        if ev == "fault":
            notify("fault", dev, f"{dev}: FAULT {(m.get('data') or {}).get('code')}")
        elif ev == "warn" and (m.get("data") or {}).get("on"):
            notify("warn_" + str((m.get("data") or {}).get("code")), dev, f"{dev}: {(m.get('data') or {}).get('code')}", once_per_s=86400)
        elif ev == "cycle_complete":
            from .aggregate import on_cycle_complete
            on_cycle_complete(dev, t, m.get("data") or {})
        elif ev == "state":
            from .aggregate import on_state_event
            on_state_event(dev, t, m)
        return "event"
    return "skip"


def _soc_alert() -> float:
    from .config import CFG
    return CFG.alerts.soc_alert


@router.post("/api/ingest")
async def ingest(request: Request):
    body = await request.json()
    msgs = body if isinstance(body, list) else [body]
    t = db.now_ms()
    ip = request.client.host if request.client else None
    # Усередині пачки — за uptime, щоб події й телеметрія лягли у правильному порядку
    msgs = sorted(msgs, key=lambda m: (int(m.get("uptime") or 0), int(m.get("seq") or 0)))
    accepted = 0
    for m in msgs:
        try:
            if store_message(m, t, ip) != "skip":
                accepted += 1
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("ingest").exception("bad message: %s", e)
    return {"ok": True, "accepted": accepted}
