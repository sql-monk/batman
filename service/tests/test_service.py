"""Приймання, розриви, ресети, агрегати, цикли — без заліза."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["BATMAN_DB"] = str(Path(tempfile.mkdtemp()) / "t.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from batman_service import db, aggregate  # noqa: E402
from batman_service.main import app  # noqa: E402

client = TestClient(app)
DEV = "t1"


def tele(seq, uptime, i1, i2=0.0, state="IDLE", u1=26.0, u2=25.0):
    return {"v": 1, "type": "telemetry", "id": DEV, "seq": seq, "uptime": uptime, "state": state,
            "b1": {"u": u1, "i": i1, "t": 24.0, "soc": 80, "sw": "on", "ah_in": 0, "ah_out": 0, "wh_in": 0, "wh_out": 0},
            "b2": {"u": u2, "i": i2, "t": 23.0, "soc": 60, "sw": "off", "ah_in": 0, "ah_out": 0, "wh_in": 0, "wh_out": 0},
            "load": {"u": 25.7, "i": 4.0}, "dps": {"ok": True, "uin": 33.0, "uout": 0, "iout": 0, "uset": 0, "iset": 0, "on": False, "cc": False, "prot": 0, "k": 0},
            "fault": None, "wifi": {"rssi": -60}, "warn": []}


def test_ingest_and_gaps():
    with client:
        db.migrate()
        r = client.post("/api/ingest", json=[{"v": 1, "type": "event", "id": DEV, "seq": 1, "uptime": 5, "event": "boot", "data": {"fw": "x", "reset_reason": 1}}])
        assert r.json()["accepted"] == 1
        assert client.post("/api/ingest", json=[tele(2, 6, -4.0), tele(3, 8, -4.0)]).json()["accepted"] == 2
        # пропуск seq 4..9
        client.post("/api/ingest", json=[tele(10, 20, -4.0)])
        gaps = [dict(g) for g in db.q("SELECT * FROM gap WHERE device_id=?", (DEV,))]
        assert any(g["kind"] == "seq_gap" and g["seq_from"] == 3 and g["seq_to"] == 10 for g in gaps)
        # ресет: uptime назад + boot
        client.post("/api/ingest", json=[{"v": 1, "type": "event", "id": DEV, "seq": 1, "uptime": 3, "event": "boot", "data": {"fw": "x", "reset_reason": 3}}])
        gaps = [dict(g) for g in db.q("SELECT * FROM gap WHERE device_id=? AND kind='reboot'", (DEV,))]
        assert len(gaps) == 1
        assert db.q1("SELECT COUNT(*) AS n FROM boot WHERE device_id=?", (DEV,))["n"] == 2
        assert client.get("/api/devices").json()[0]["id"] == DEV
        assert client.get("/health").json()["ok"]


def test_aggregate_integral():
    """1 год розряду 4 А → ah_out ≈ 4; потім година заряду 10 А → ah_in ≈ 10."""
    dev = "t2"
    db.migrate()
    base = (1_700_000_000_000 // 3600_000) * 3600_000   # рівна година
    rows = []
    for k in range(0, 3600, 10):   # раз на 10 с
        rows.append((dev, base + k * 1000, k, k, "IDLE", 26.0, -4.0))
    for k in range(3600, 7200, 10):
        rows.append((dev, base + k * 1000, k, k, "CHG_B1_CC", 27.0, 10.0))
    db.x("INSERT OR IGNORE INTO device(id,name,first_seen,last_seen) VALUES(?,?,?,?)", (dev, dev, base, base))
    db.xmany("INSERT INTO sample(device_id,t,seq,uptime,state,b1_u,b1_i) VALUES(?,?,?,?,?,?,?)", rows)
    a1 = aggregate._agg_window(dev, 1, base, base + 3600_000)
    a2 = aggregate._agg_window(dev, 1, base + 3600_000, base + 7200_000)
    assert abs(a1["ah_out"] - 4.0) < 0.05 and a1["ah_in"] < 0.01
    assert abs(a2["ah_in"] - 10.0) < 0.05 and a2["s_charge"] >= 3500
    aggregate.run_once()
    got = db.q("SELECT * FROM agg_hour WHERE device_id=? AND bat=1 ORDER BY t_start", (dev,))
    assert len(got) >= 2 and abs(got[1]["ah_in"] - 10.0) < 0.05


def test_cycles():
    dev = "t3"
    db.migrate()
    t = 1_700_000_000_000
    db.x("INSERT OR IGNORE INTO device(id,name,first_seen,last_seen) VALUES(?,?,?,?)", (dev, dev, t, t))
    aggregate.on_state_event(dev, t, {"from": "IDLE", "to": "CHG_B1_CC", "reason": "user"})
    aggregate.on_state_event(dev, t + 1000, {"from": "CHG_B1_CC", "to": "CHG_B1_CV", "reason": "u_reached"})
    aggregate.on_cycle_complete(dev, t + 5000_000, {"bat": 1, "ah_in": 12.5, "ah_out": 0.0, "wh_in": 350, "wh_out": 0})
    aggregate.on_state_event(dev, t + 5000_000, {"from": "CHG_B1_CV", "to": "IDLE", "reason": "tail_current"})
    c = [dict(r) for r in db.q("SELECT * FROM cycle WHERE device_id=?", (dev,))]
    assert len(c) == 1 and c[0]["ah_in"] == 12.5 and c[0]["t_end"] is not None and c[0]["end_reason"] == "complete"
