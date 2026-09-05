"""config.toml + змінні середовища. BATMAN_CONFIG — шлях до файлу (типово ./config.toml)."""
from __future__ import annotations
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Server:
    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str = ""


@dataclass
class Db:
    path: str = "data/batman.db"


@dataclass
class Discovery:
    mdns: bool = True
    udp: bool = True
    udp_interval_s: int = 60
    manual: list = field(default_factory=list)


@dataclass
class Retention:
    raw_days: int = 90
    min_days: int = 365


@dataclass
class Telegram:
    enabled: bool = False
    token: str = ""
    chat_id: str = ""


@dataclass
class Email:
    enabled: bool = False
    smtp: str = ""
    user: str = ""
    password: str = ""
    from_: str = ""
    to: str = ""


@dataclass
class Alerts:
    soc_alert: float = 20
    offline_min: int = 5
    telegram: Telegram = field(default_factory=Telegram)
    email: Email = field(default_factory=Email)


@dataclass
class Config:
    server: Server = field(default_factory=Server)
    db: Db = field(default_factory=Db)
    discovery: Discovery = field(default_factory=Discovery)
    retention: Retention = field(default_factory=Retention)
    alerts: Alerts = field(default_factory=Alerts)
    base_dir: Path = field(default_factory=lambda: Path.cwd())


def _fill(obj, d: dict):
    for k, v in d.items():
        key = "from_" if k == "from" else k
        if not hasattr(obj, key):
            continue
        cur = getattr(obj, key)
        if isinstance(v, dict) and not isinstance(cur, (dict, list)):
            _fill(cur, v)
        else:
            setattr(obj, key, v)


def load(path: str | None = None) -> Config:
    cfg = Config()
    p = Path(path or os.environ.get("BATMAN_CONFIG", "config.toml"))
    if p.exists():
        with p.open("rb") as f:
            _fill(cfg, tomllib.load(f))
        cfg.base_dir = p.resolve().parent
    if os.environ.get("BATMAN_DB"):
        cfg.db.path = os.environ["BATMAN_DB"]
    if os.environ.get("BATMAN_PUBLIC_URL"):
        cfg.server.public_url = os.environ["BATMAN_PUBLIC_URL"]
    return cfg


CFG = load()
