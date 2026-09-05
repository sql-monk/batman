"""Сповіщення: журнал завжди; Telegram і e-mail — якщо ввімкнено. Антидребезг: once_per_s на (kind, device)."""
from __future__ import annotations
import logging
import smtplib
import threading
import time
from email.message import EmailMessage
import httpx
from . import db
from .config import CFG

log = logging.getLogger("notify")
_last: dict[tuple[str, str | None], float] = {}
_lock = threading.Lock()


def notify(kind: str, device_id: str | None, text: str, once_per_s: float = 0) -> None:
    key = (kind, device_id)
    now = time.time()
    with _lock:
        if once_per_s and now - _last.get(key, 0) < once_per_s:
            return
        _last[key] = now
    log.warning("[%s] %s", kind, text)
    nid = db.x("INSERT INTO notification(t,device_id,kind,text,sent) VALUES(?,?,?,?,0)", (db.now_ms(), device_id, kind, text))
    threading.Thread(target=_send, args=(nid, text), daemon=True).start()


def _send(nid: int, text: str) -> None:
    sent = False
    tg = CFG.alerts.telegram
    if tg.enabled and tg.token and tg.chat_id:
        try:
            httpx.post(f"https://api.telegram.org/bot{tg.token}/sendMessage", json={"chat_id": tg.chat_id, "text": text}, timeout=10)
            sent = True
        except Exception as e:  # noqa: BLE001
            log.error("telegram: %s", e)
    em = CFG.alerts.email
    if em.enabled and em.smtp and em.to:
        try:
            host, _, port = em.smtp.partition(":")
            msg = EmailMessage()
            msg["Subject"] = "batman: " + text[:60]
            msg["From"] = em.from_
            msg["To"] = em.to
            msg.set_content(text)
            with smtplib.SMTP(host, int(port or 25), timeout=15) as s:
                s.starttls()
                if em.user:
                    s.login(em.user, em.password)
                s.send_message(msg)
            sent = True
        except Exception as e:  # noqa: BLE001
            log.error("email: %s", e)
    if sent:
        db.x("UPDATE notification SET sent=1 WHERE id=?", (nid,))
