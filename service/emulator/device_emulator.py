"""Емулятор пристрою batman за docs/protocol.md: REST на порту, UDP-відповідач, телеметрія на sink.

    python emulator/device_emulator.py --id test01 --port 8081 --sink http://localhost:8000/api/ingest [--fast 60]

--fast N: час у моделі йде в N разів швидше (заряд 50 А·год за хвилини, а не години).
"""
from __future__ import annotations
import argparse
import json
import math
import random
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

FW = "0.1.0-emu"


class Model:
    def __init__(self, dev_id: str, fast: float):
        self.id = dev_id
        self.fast = fast
        self.t0 = time.time()
        self.seq = 0
        self.state = "IDLE"
        self.state_since = self.t0
        self.fault = None
        self.sw = [True, False]
        self.k = 0
        self.dps = {"ok": True, "uin": 33.0, "uout": 0.0, "iout": 0.0, "uset": 20.0, "iset": 1.0, "on": False, "cc": False, "prot": 0}
        self.cnom = [50.0, 65.0]
        self.soc = [72.0, 55.0]
        self.ah = [[0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]]   # in, out, win, wout за цикл
        self.tot = [[300.0, 290.0], [800.0, 780.0]]
        self.cycles = [12, 31]
        self.temp = [24.0, 23.0]
        self.load_i = 4.3
        self.sink = None
        self.interval = 2
        self.cfg = {"v": 1, "profile": {"lifepo4": {"i_cc": 10.0, "u_cv": 28.8, "i_tail": 2.5, "t_min": 0, "t_max": 45},
                    "pb": {"i_bulk": 10.0, "u_abs": 28.8, "u_float": 27.4, "i_abs_end": 1.3, "tc_v_per_c": -0.036, "t_ref": 25, "t_max": 45}},
                    "discharge": {"1": {"u_off": 24.0, "u_on": 25.2}, "2": {"u_off": 23.0, "u_on": 24.6}},
                    "policy": {"charge_order": "lowest_soc", "auto": False, "rest_min": 10},
                    "bat": {"1": {"chem": "lifepo4", "c_nom": 50.0}, "2": {"chem": "pb", "c_nom": 65.0}},
                    "limits": {"i_set_max": 12.0, "u_set_max": 29.8}, "sink": {"url": "", "interval_s": 2}, "oled": {"timeout_s": 120}}
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.last = time.time()
        self.emit("boot", {"data": {"fw": FW, "reset_reason": 1, "restored": False}})

    def uptime(self):
        return int(time.time() - self.t0)

    def emit(self, event: str, extra: dict):
        self.seq += 1
        e = {"v": 1, "type": "event", "id": self.id, "seq": self.seq, "uptime": self.uptime(), "event": event, **extra}
        self.events.append(e)
        self.pending.append(e) if hasattr(self, "pending") else None

    def set_state(self, s: str, reason: str):
        if s == self.state:
            return
        self.emit("state", {"from": self.state, "to": s, "reason": reason, "data": {"duration_s": int(time.time() - self.state_since)}})
        self.state, self.state_since = s, time.time()

    def ocv(self, b: int) -> float:
        s = self.soc[b] / 100
        if b == 0:   # LiFePO4 8S: плоска полиця
            return 25.0 + 1.6 * min(1, s * 1.1) + (0.9 if s > 0.97 else 0) + 0.2 * s
        return 24.0 + 2.6 * s   # свинець

    def step(self, dt_real: float):
        dt = dt_real * self.fast
        with self.lock:
            chg = 1 if self.state.startswith("CHG_B1") else 2 if self.state.startswith("CHG_B2") else 0
            u, i = [0.0, 0.0], [0.0, 0.0]
            # розряд: навантаження бере з гілки з вищою напругою (діодне АБО); логіка 0,08 А
            ocv = [self.ocv(0), self.ocv(1)]
            on = [self.sw[b] for b in range(2)]
            src = None
            if on[0] and on[1]:
                src = 0 if ocv[0] >= ocv[1] else 1
            elif on[0] or on[1]:
                src = 0 if on[0] else 1
            load = self.load_i + random.uniform(-0.1, 0.1) if src is not None else 0.0
            for b in range(2):
                i[b] = -(load if src == b else 0.0) - (0.08 if b == (0 if ocv[0] >= ocv[1] else 1) else 0.0)
            # заряд
            if chg and self.dps["on"]:
                b = chg - 1
                prof = self.cfg["profile"]["lifepo4" if b == 0 else "pb"]
                tgt = self.dps["uset"] - 0.45
                full = self.soc[b] >= 99.5
                ic = min(self.dps["iset"], max(0.05, (tgt - ocv[b]) * 25))
                if full:
                    ic = max(0.1, ic * 0.5)
                i[b] += ic
                self.dps["iout"] = round(ic, 2)
                self.dps["uout"] = round(min(self.dps["uset"], ocv[b] + ic * 0.05 + 0.45), 2)
                self.dps["cc"] = ic >= self.dps["iset"] - 0.05
                ub = ocv[b] + ic * 0.04
                # стейт-машина за профілем
                if self.state == "CHG_B1_CC" and ub >= prof["u_cv"] - 0.05:
                    self.set_state("CHG_B1_CV", "u_reached")
                if self.state == "CHG_B2_BULK" and ub >= prof["u_abs"] - 0.05:
                    self.set_state("CHG_B2_ABS", "u_reached")
                if self.state == "CHG_B1_CV" and ic <= prof["i_tail"]:
                    self.complete(0)
                    self.stop("tail_current")
                if self.state == "CHG_B2_ABS" and ic <= prof["i_abs_end"]:
                    self.complete(1)
                    self.set_state("CHG_B2_FLOAT", "tail_current")
                    self.dps["uset"] = prof["u_float"]
            else:
                self.dps["iout"] = 0.0
                self.dps["uout"] = 0.0
            for b in range(2):
                u[b] = ocv[b] + i[b] * 0.04 + random.uniform(-0.01, 0.01)
                q = i[b] * dt / 3600
                if q > 0:
                    self.ah[b][0] += q; self.ah[b][2] += q * u[b]; self.tot[b][0] += q
                    self.soc[b] = min(100, self.soc[b] + q * (0.98 if b == 0 else 0.9) / self.cnom[b] * 100)
                else:
                    self.ah[b][1] -= q; self.ah[b][3] -= q * u[b]; self.tot[b][1] -= q
                    self.soc[b] = max(0, self.soc[b] + q / self.cnom[b] * 100)
                self.temp[b] += (0.002 * abs(i[b]) - 0.001 * (self.temp[b] - 23)) * dt
                if self.sw[b] and u[b] < self.cfg["discharge"][str(b + 1)]["u_off"]:
                    self.sw[b] = False
                    self.emit("switch", {"data": {"bat": b + 1, "sw": "off", "by": "u_low"}})
            self._u, self._i = u, i

    def complete(self, b: int):
        self.emit("cycle_complete", {"data": {"bat": b + 1, "ah_in": round(self.ah[b][0], 3), "ah_out": round(self.ah[b][1], 3),
                                              "wh_in": round(self.ah[b][2], 1), "wh_out": round(self.ah[b][3], 1), "cycles": self.cycles[b] + 1}})
        self.ah[b] = [0.0, 0.0, 0.0, 0.0]
        self.cycles[b] += 1
        self.soc[b] = 100

    def start(self, bat: int) -> tuple[int, str]:
        if self.fault:
            return 423, "fault active"
        if self.state.startswith("CHG"):
            return 409, "already charging"
        b = bat - 1
        prof = self.cfg["profile"]["lifepo4" if b == 0 else "pb"]
        self.k = bat
        self.dps["uset"] = round(min(self.ocv(b) + 0.5, (prof["u_cv"] if b == 0 else prof["u_abs"]) + 0.6), 2)
        self.dps["iset"] = prof["i_cc"] if b == 0 else prof["i_bulk"]
        self.dps["on"] = True
        self.set_state("CHG_B1_CC" if bat == 1 else "CHG_B2_BULK", "user")
        return 200, ""

    def stop(self, reason: str):
        self.dps["on"] = False
        self.k = 0
        self.set_state("IDLE", reason)

    def telemetry(self, with_seq=True) -> dict:
        u = getattr(self, "_u", [self.ocv(0), self.ocv(1)])
        i = getattr(self, "_i", [0.0, 0.0])
        if with_seq:
            self.seq += 1

        def bat(b):
            return {"u": round(u[b], 2), "i": round(i[b], 2), "t": round(self.temp[b], 1), "soc": round(self.soc[b], 1),
                    "sw": "on" if self.sw[b] else "off", "ah_in": round(self.ah[b][0], 3), "ah_out": round(self.ah[b][1], 3),
                    "wh_in": round(self.ah[b][2], 1), "wh_out": round(self.ah[b][3], 1),
                    "ah_in_tot": round(self.tot[b][0], 1), "ah_out_tot": round(self.tot[b][1], 1), "cycles": self.cycles[b]}
        src = max(range(2), key=lambda b: u[b] if self.sw[b] else -1)
        return {"v": 1, "type": "telemetry", "id": self.id, "seq": self.seq, "uptime": self.uptime(), "state": self.state,
                "b1": bat(0), "b2": bat(1), "load": {"u": round(u[src] - 0.3, 2) if any(self.sw) else 0.0, "i": round(-sum(min(0, x) for x in i) - 0.08, 2)},
                "dps": {**self.dps, "k": self.k}, "fault": self.fault, "wifi": {"rssi": -58 + random.randint(-3, 3)}, "warn": []}


M: Model


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/status":
            self._send(200, {"id": M.id, "fw": FW, "v": 1, "uptime": M.uptime(), "state": M.state, "fault": M.fault,
                             "sink": {"url": M.sink or "", "interval_s": M.interval, "ok": bool(M.sink)}, "wifi": {"rssi": -58}, "heap": 200000})
        elif p == "/telemetry":
            self._send(200, M.telemetry(False))
        elif p == "/config":
            M.cfg["sink"] = {"url": M.sink or "", "interval_s": M.interval}
            self._send(200, M.cfg)
        elif p == "/events":
            self._send(200, M.events[-100:])
        elif p == "/calibration":
            self._send(200, {"zero_v": [1.65, 1.65, 1.65], "gain": [1, 1, 1], "ugain": [1, 1, 1]})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        j = self._body()
        if p == "/sink":
            M.sink = j.get("url")
            M.interval = int(j.get("interval_s") or 2)
            print("sink ->", M.sink)
            self._send(200, {"ok": True})
        elif p == "/control":
            cmd = j.get("cmd")
            with M.lock:
                if cmd == "charge_start":
                    code, err = M.start(int(j.get("bat") or 0))
                elif cmd == "charge_stop":
                    if M.state.startswith("CHG"):
                        M.stop("user"); code, err = 200, ""
                    else:
                        code, err = 409, "not charging"
                elif cmd == "switch":
                    b = int(j.get("bat")) - 1
                    M.sw[b] = bool(j.get("on"))
                    M.emit("switch", {"data": {"bat": b + 1, "sw": "on" if M.sw[b] else "off", "by": "user"}})
                    code, err = 200, ""
                elif cmd == "fault_clear":
                    M.fault = None; M.set_state("IDLE", "user"); code, err = 200, ""
                elif cmd == "soc_set":
                    M.soc[int(j["bat"]) - 1] = float(j["soc"]); code, err = 200, ""
                elif cmd == "counters_reset":
                    M.ah[int(j["bat"]) - 1] = [0.0] * 4; code, err = 200, ""
                elif cmd in ("calibrate_zero", "calibrate_gain", "calibrate_ugain", "reboot"):
                    code, err = 200, ""
                else:
                    code, err = 400, "unknown cmd"
            self._send(code, {"ok": code == 200} if code == 200 else {"ok": False, "error": err})
        elif p == "/config":
            for k, v in j.items():
                if k == "limits":
                    self._send(400, {"ok": False, "error": "limits are read-only"}); return
                if isinstance(v, dict) and isinstance(M.cfg.get(k), dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, dict) and isinstance(M.cfg[k].get(k2), dict):
                            M.cfg[k][k2].update(v2)
                        else:
                            M.cfg[k][k2] = v2
                else:
                    M.cfg[k] = v
            M.emit("config", {"data": {"changed": ",".join(j.keys())}})
            self._send(200, M.cfg)
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_DELETE(self):
        if self.path == "/sink":
            M.sink = None
            self._send(200, {"ok": True})
        else:
            self._send(404, {})


def udp_loop(port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 47474))
    while True:
        data, addr = s.recvfrom(64)
        if data.startswith(b"BATMAN?"):
            ip = socket.gethostbyname(socket.gethostname())
            s.sendto(json.dumps({"v": 1, "id": M.id, "ip": ip, "port": port, "fw": FW}).encode(), addr)


def sender_loop():
    buf: list[dict] = []
    M.pending = buf
    last_t = 0.0
    while True:
        M.step(time.time() - M.last)
        M.last = time.time()
        if M.sink and time.time() - last_t >= M.interval:
            last_t = time.time()
            buf.append(M.telemetry())
            try:
                r = httpx.post(M.sink, json=buf[:100], timeout=3)
                if r.status_code == 200:
                    del buf[:100]
            except Exception as e:  # noqa: BLE001
                print("sink error:", e)
            if len(buf) > 300:
                del buf[:len(buf) - 300]
        time.sleep(0.5)


def main():
    global M
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="emu001")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--sink", default=None)
    ap.add_argument("--fast", type=float, default=1.0)
    ap.add_argument("--no-udp", action="store_true")
    a = ap.parse_args()
    M = Model(a.id, a.fast)
    M.sink = a.sink
    if not a.no_udp:
        threading.Thread(target=udp_loop, args=(a.port,), daemon=True).start()
    threading.Thread(target=sender_loop, daemon=True).start()
    print(f"emulator {M.id} on :{a.port}, sink={a.sink}, fast x{a.fast}")
    ThreadingHTTPServer(("", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
