"""Пошук пристроїв: mDNS (_batman._tcp), UDP-broadcast BATMAN? на 47474, ручний список."""
from __future__ import annotations
import json
import logging
import socket
import threading
from . import db
from .config import CFG

log = logging.getLogger("discovery")
UDP_PORT = 47474


def found(dev_id: str, ip: str, port: int = 80, fw: str | None = None) -> None:
    t = db.now_ms()
    row = db.q1("SELECT id, status FROM device WHERE id=?", (dev_id,))
    if row is None:
        db.x("INSERT INTO device(id,name,ip,port,fw,status,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?)",
             (dev_id, "batman-" + dev_id, ip, port, fw, "discovered", t, t))
        log.info("found %s at %s:%s", dev_id, ip, port)
    else:
        db.x("UPDATE device SET ip=?, port=?, fw=COALESCE(?,fw) WHERE id=?", (ip, port, fw, dev_id))


def udp_scan_once(timeout: float = 2.0) -> list[dict]:
    res = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(timeout)
    try:
        s.sendto(b"BATMAN?", ("255.255.255.255", UDP_PORT))
        while True:
            try:
                data, addr = s.recvfrom(512)
            except socket.timeout:
                break
            try:
                j = json.loads(data.decode())
                if j.get("v") == 1 and "id" in j:
                    j["ip"] = j.get("ip") or addr[0]
                    res.append(j)
                    found(j["id"], j["ip"], int(j.get("port") or 80), j.get("fw"))
            except Exception:  # noqa: BLE001
                pass
    finally:
        s.close()
    return res


class _Listener:
    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if not info:
            return
        props = {k.decode() if isinstance(k, bytes) else k: (v.decode() if isinstance(v, bytes) else v) for k, v in (info.properties or {}).items()}
        ips = info.parsed_addresses()
        if ips and props.get("id"):
            found(props["id"], ips[0], info.port or 80, props.get("fw"))

    def update_service(self, zc, type_, name):
        self.add_service(zc, type_, name)

    def remove_service(self, zc, type_, name):
        pass


def loop(stop: threading.Event) -> None:
    zc = browser = None
    if CFG.discovery.mdns:
        try:
            from zeroconf import ServiceBrowser, Zeroconf
            zc = Zeroconf()
            browser = ServiceBrowser(zc, "_batman._tcp.local.", _Listener())
        except Exception as e:  # noqa: BLE001
            log.error("mdns: %s", e)
    for m in CFG.discovery.manual or []:
        try:
            found(m[0], m[1], int(m[2]) if len(m) > 2 else 80)
            db.x("UPDATE device SET status='manual' WHERE id=? AND status='discovered'", (m[0],))
        except Exception:  # noqa: BLE001
            pass
    while not stop.is_set():
        if CFG.discovery.udp:
            try:
                udp_scan_once()
            except Exception as e:  # noqa: BLE001
                log.error("udp: %s", e)
        stop.wait(max(5, CFG.discovery.udp_interval_s))
    if zc:
        zc.close()
