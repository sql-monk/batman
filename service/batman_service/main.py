"""FastAPI: сторінки, API, SSE, фонові потоки (пошук, агрегати, контроль зв'язку)."""
from __future__ import annotations
import asyncio
import csv
import io
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from . import db, ingest, discovery, aggregate, devices
from .config import CFG
from . import __version__

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB = Path(__file__).resolve().parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))
_stop = threading.Event()
_threads: list[threading.Thread] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.migrate()
    for target, name in ((discovery.loop, "discovery"), (aggregate.loop, "aggregate"), (devices.watchdog, "watchdog")):
        t = threading.Thread(target=target, args=(_stop,), name=name, daemon=True)
        t.start()
        _threads.append(t)
    yield
    _stop.set()


app = FastAPI(title="batman", version=__version__, lifespan=lifespan)
app.include_router(ingest.router)
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")


def _dev_or_404(dev_id: str):
    d = db.q1("SELECT * FROM device WHERE id=?", (dev_id,))
    if not d:
        raise HTTPException(404, "unknown device")
    return dict(d)


def _last_sample(dev_id: str) -> dict | None:
    r = db.q1("SELECT raw, t FROM sample WHERE device_id=? ORDER BY t DESC LIMIT 1", (dev_id,))
    if not r:
        return None
    j = json.loads(r["raw"])
    j["_t"] = r["t"]
    return j


def _overview() -> list[dict]:
    out = []
    for d in db.q("SELECT * FROM device ORDER BY name"):
        dd = dict(d)
        dd["last"] = _last_sample(d["id"])
        dd["online"] = bool(d["last_seen"] and db.now_ms() - d["last_seen"] < 15000)
        out.append(dd)
    return out


# ---------- сторінки ----------
@app.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"devices": _overview(), "cfg": CFG})


@app.get("/d/{dev_id}", response_class=HTMLResponse)
def page_device(request: Request, dev_id: str):
    return templates.TemplateResponse(request, "device.html", {"dev": _dev_or_404(dev_id), "last": _last_sample(dev_id)})


@app.get("/d/{dev_id}/cycles", response_class=HTMLResponse)
def page_cycles(request: Request, dev_id: str):
    rows = [dict(r) for r in db.q("SELECT * FROM cycle WHERE device_id=? ORDER BY t_start DESC LIMIT 200", (dev_id,))]
    return templates.TemplateResponse(request, "cycles.html", {"dev": _dev_or_404(dev_id), "cycles": rows})


@app.get("/d/{dev_id}/events", response_class=HTMLResponse)
def page_events(request: Request, dev_id: str, kind: str = ""):
    sql = "SELECT * FROM event WHERE device_id=?" + (" AND event=?" if kind else "") + " ORDER BY t DESC LIMIT 300"
    rows = [dict(r) for r in db.q(sql, (dev_id, kind) if kind else (dev_id,))]
    return templates.TemplateResponse(request, "events.html", {"dev": _dev_or_404(dev_id), "events": rows, "kind": kind})


@app.get("/d/{dev_id}/control", response_class=HTMLResponse)
def page_control(request: Request, dev_id: str):
    dev = _dev_or_404(dev_id)
    code, cfg = devices.proxy(dev_id, "/config")
    return templates.TemplateResponse(request, "control.html", {"dev": dev, "config": cfg if code == 200 else None, "last": _last_sample(dev_id)})


@app.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return templates.TemplateResponse(request, "settings.html", {"cfg": CFG, "devices": _overview()})


# ---------- API ----------
@app.get("/api/devices")
def api_devices():
    return _overview()


@app.post("/api/discover")
def api_discover():
    return {"ok": True, "found": discovery.udp_scan_once()}


@app.post("/api/devices/manual")
async def api_manual(request: Request):
    j = await request.json()
    ip, port = j.get("ip"), int(j.get("port") or 80)
    if not ip:
        raise HTTPException(400, "ip")
    import httpx
    try:
        st = httpx.get(f"http://{ip}:{port}/status", timeout=5).json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"no answer: {e}")
    discovery.found(st["id"], ip, port, st.get("fw"))
    db.x("UPDATE device SET status='manual' WHERE id=? AND status='discovered'", (st["id"],))
    return {"ok": True, "id": st["id"]}


@app.post("/api/d/{dev_id}/connect")
async def api_connect(dev_id: str, request: Request):
    _dev_or_404(dev_id)
    j = {}
    try:
        j = await request.json()
    except Exception:  # noqa: BLE001
        pass
    return devices.connect(dev_id, j.get("public_url"))


@app.post("/api/d/{dev_id}/control")
async def api_control(dev_id: str, request: Request):
    _dev_or_404(dev_id)
    code, res = devices.control(dev_id, await request.json())
    return JSONResponse(res if isinstance(res, dict) else {"raw": res}, status_code=code)


@app.get("/api/d/{dev_id}/config")
def api_config_get(dev_id: str):
    _dev_or_404(dev_id)
    code, res = devices.proxy(dev_id, "/config")
    return JSONResponse(res if isinstance(res, dict) else {"raw": res}, status_code=code)


@app.post("/api/d/{dev_id}/config")
async def api_config_set(dev_id: str, request: Request):
    _dev_or_404(dev_id)
    code, res = devices.set_config(dev_id, await request.json())
    return JSONResponse(res if isinstance(res, dict) else {"raw": res}, status_code=code)


@app.get("/api/d/{dev_id}/status")
def api_status(dev_id: str):
    _dev_or_404(dev_id)
    code, res = devices.proxy(dev_id, "/status", timeout=4)
    return JSONResponse(res if isinstance(res, dict) else {"raw": res}, status_code=code)


SERIES_COLS = ["b1_u", "b1_i", "b1_soc", "b1_t", "b2_u", "b2_i", "b2_soc", "b2_t", "load_u", "load_i", "dps_uin", "dps_uout", "dps_iout"]


@app.get("/api/d/{dev_id}/series")
def api_series(dev_id: str, hours: float = Query(1, gt=0, le=24 * 60), to: int | None = None):
    """Ряди для uPlot: [t_s, col1, col2, …]; ≤ 24 год — сирі (проріджені до ~2000 точок), далі — з agg_hour."""
    _dev_or_404(dev_id)
    t1 = to or db.now_ms()
    t0 = int(t1 - hours * 3600_000)
    if hours <= 24:
        n = db.q1("SELECT COUNT(*) AS n FROM sample WHERE device_id=? AND t BETWEEN ? AND ?", (dev_id, t0, t1))["n"]
        step = max(1, n // 2000)
        rows = db.q(f"SELECT t,{','.join(SERIES_COLS)},state FROM sample WHERE device_id=? AND t BETWEEN ? AND ? AND (id % ?)=0 ORDER BY t",
                    (dev_id, t0, t1, step))
        data = [[r["t"] / 1000 for r in rows]] + [[r[c] for r in rows] for c in SERIES_COLS]
        states = [r["state"] for r in rows]
        return {"cols": ["t"] + SERIES_COLS, "data": data, "states": states, "source": "raw"}
    rows = db.q("SELECT bat, t_start, u_avg, i_max, i_min, soc_min, t_max, ah_in, ah_out FROM agg_hour WHERE device_id=? AND t_start BETWEEN ? AND ? ORDER BY t_start", (dev_id, t0, t1))
    by_t: dict[int, dict] = {}
    for r in rows:
        by_t.setdefault(r["t_start"], {})[r["bat"]] = dict(r)
    ts = sorted(by_t)
    def col(b, k):
        return [by_t[t].get(b, {}).get(k) for t in ts]
    data = [[t / 1000 for t in ts], col(1, "u_avg"), col(1, "i_max"), col(1, "soc_min"), col(1, "t_max"),
            col(2, "u_avg"), col(2, "i_max"), col(2, "soc_min"), col(2, "t_max"), [None] * len(ts), [None] * len(ts), [None] * len(ts), [None] * len(ts), [None] * len(ts)]
    return {"cols": ["t"] + SERIES_COLS, "data": data, "states": [], "source": "agg_hour"}


@app.get("/api/d/{dev_id}/events")
def api_events(dev_id: str, limit: int = 200, since: int = 0):
    _dev_or_404(dev_id)
    return [dict(r) for r in db.q("SELECT * FROM event WHERE device_id=? AND t>? ORDER BY t DESC LIMIT ?", (dev_id, since, limit))]


@app.get("/api/d/{dev_id}/cycles")
def api_cycles(dev_id: str, limit: int = 200):
    _dev_or_404(dev_id)
    return [dict(r) for r in db.q("SELECT * FROM cycle WHERE device_id=? ORDER BY t_start DESC LIMIT ?", (dev_id, limit))]


@app.get("/api/d/{dev_id}/agg")
def api_agg(dev_id: str, res: str = "day", days: int = 30):
    _dev_or_404(dev_id)
    table = "agg_day" if res == "day" else "agg_hour"
    t0 = db.now_ms() - days * 86400_000
    return [dict(r) for r in db.q(f"SELECT * FROM {table} WHERE device_id=? AND t_start>=? ORDER BY t_start", (dev_id, t0))]


@app.get("/api/d/{dev_id}/export.csv")
def api_export(dev_id: str, what: str = "samples", hours: float = 24, step_s: int = 10):
    _dev_or_404(dev_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    if what == "samples":
        t0 = db.now_ms() - hours * 3600_000
        cols = ["t", "state"] + SERIES_COLS + ["b1_ah_in", "b1_ah_out", "b2_ah_in", "b2_ah_out", "warn"]
        w.writerow(cols)
        last_t = 0
        for r in db.q(f"SELECT {','.join(cols)} FROM sample WHERE device_id=? AND t>=? ORDER BY t", (dev_id, t0)):
            if r["t"] - last_t >= step_s * 1000:
                w.writerow([r[c] for c in cols])
                last_t = r["t"]
    elif what in ("agg_hour", "agg_day"):
        rows = db.q(f"SELECT * FROM {what} WHERE device_id=? ORDER BY t_start", (dev_id,))
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
    elif what == "cycles":
        rows = db.q("SELECT * FROM cycle WHERE device_id=? ORDER BY t_start", (dev_id,))
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
    elif what == "events":
        rows = db.q("SELECT * FROM event WHERE device_id=? ORDER BY t", (dev_id,))
        if rows:
            w.writerow(rows[0].keys())
            for r in rows:
                w.writerow(list(r))
    else:
        raise HTTPException(400, "what")
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{dev_id}-{what}.csv"'})


@app.get("/api/stream")
async def api_stream():
    async def gen():
        while True:
            yield "data: " + json.dumps(_overview(), default=str) + "\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"ok": True, "version": __version__, "devices": db.q1("SELECT COUNT(*) AS n FROM device")["n"]}
