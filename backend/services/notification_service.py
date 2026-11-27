import os
import smtplib
import threading
import time
import logging
from email.message import EmailMessage
from urllib.parse import quote

import requests

from .database import get_db_connection

log = logging.getLogger("marketmind.notifications")

def _smtp_send(to_email: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST", "")
    user = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)
    if not all([host, user, password, sender]):
        raise RuntimeError("SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM are required.")
    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email
    message.set_content(body)
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(message)

def send_email_otp(to_email: str, otp: str):
    _smtp_send(to_email, "MarketMind AI verification code",
               f"Your MarketMind AI verification code is {otp}. It expires in 10 minutes. Do not share it.")

def send_twilio_verification(phone: str, otp: str):
    # SMS OTP. WhatsApp OTP can be enabled through Twilio Verify by setting
    # TWILIO_VERIFY_WHATSAPP=true and configuring WhatsApp as a Verify channel.
    account = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    service = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")
    if not all([account, token, service]):
        raise RuntimeError("Twilio Verify credentials are not configured.")
    channel = "whatsapp" if os.getenv("TWILIO_VERIFY_WHATSAPP", "false").lower() == "true" else "sms"
    url = f"https://verify.twilio.com/v2/Services/{service}/Verifications"
    response = requests.post(url, auth=(account, token), data={"To": phone, "Channel": channel}, timeout=20)
    response.raise_for_status()

def verify_twilio_code(phone: str, otp: str) -> bool:
    account = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    service = os.getenv("TWILIO_VERIFY_SERVICE_SID", "")
    if not all([account, token, service]):
        raise RuntimeError("Twilio Verify credentials are not configured.")
    url = f"https://verify.twilio.com/v2/Services/{service}/VerificationCheck"
    response = requests.post(url, auth=(account, token), data={"To": phone, "Code": otp}, timeout=20)
    response.raise_for_status()
    return response.json().get("status") == "approved"

def send_twilio_message(to: str, body: str, channel: str):
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_number = os.getenv("TWILIO_WHATSAPP_FROM" if channel == "whatsapp" else "TWILIO_SMS_FROM", "")
    if not all([sid, token, from_number]):
        raise RuntimeError(f"Twilio {channel} sender is not configured.")
    if channel == "whatsapp":
        if not from_number.startswith("whatsapp:"):
            from_number = "whatsapp:" + from_number
        if not to.startswith("whatsapp:"):
            to = "whatsapp:" + to
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {"From": from_number, "To": to}
    content_sid = os.getenv("TWILIO_WHATSAPP_CONTENT_SID", "") if channel == "whatsapp" else ""
    if content_sid:
        data["ContentSid"] = content_sid
        # Approved template must contain one {{1}} variable for the signal text.
        data["ContentVariables"] = '{"1":' + __import__("json").dumps(body) + '}'
    else:
        data["Body"] = body
    response = requests.post(url, auth=(sid, token), data=data, timeout=20)
    response.raise_for_status()
    return response.json().get("sid")

def _signal_message(signal):
    fields = [
        "MarketMind AI — New Signal",
        f"Signal: {signal.get('action')}",
        f"Score: {signal.get('score')}%",
        f"Base Score: {signal.get('base_score')}%",
        f"Expiry: {signal.get('expiry')}",
        f"Strike: {signal.get('strike')} {signal.get('option_type')}",
        f"Symbol: {signal.get('trading_symbol')}",
        f"Initial LTP: {signal.get('initial_ltp')}",
        f"OI: {signal.get('oi')}",
        f"OI Change: {signal.get('oi_change')} ({signal.get('oi_change_pct')}%)",
        f"Signal ID: {signal.get('unique_id')}",
        "Educational signal only; not investment advice."
    ]
    return "\n".join(str(x) for x in fields)

def enqueue_signal_notification(signal: dict):
    """Persist a single event after Excel write; duplicate unique_id is ignored."""
    signal_id = str(signal["unique_id"])
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO mm_signal_outbox(signal_id, payload, status, created_at)
            VALUES (%s, %s::jsonb, 'pending', NOW())
            ON CONFLICT (signal_id) DO NOTHING
        """, (signal_id, __import__("json").dumps(signal, default=str)))

def _deliver_one():
    with get_db_connection() as conn:
        event = conn.execute("""
            SELECT signal_id, payload
            FROM mm_signal_outbox
            WHERE (status IN ('pending', 'retry') AND next_attempt_at <= NOW())
               OR (status='processing' AND created_at < NOW() - INTERVAL '5 minutes')
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        """).fetchone()
        if not event:
            return False
        conn.execute("""
            UPDATE mm_signal_outbox SET status='processing', attempts=attempts+1
            WHERE signal_id=%s
        """, (event["signal_id"],))
        # Keep payload in Python after transaction commits.
        payload = event["payload"]
        signal_id = event["signal_id"]

    body = _signal_message(payload)
    # Snapshot eligible recipients, one row per user/channel, idempotent.
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO mm_notification_deliveries(signal_id, user_id, channel, destination, status)
            SELECT %s, id, 'email', email, 'pending'
            FROM mm_users WHERE is_active=true AND email_verified=true
            ON CONFLICT (signal_id, user_id, channel) DO NOTHING
        """, (signal_id,))
        conn.execute("""
            INSERT INTO mm_notification_deliveries(signal_id, user_id, channel, destination, status)
            SELECT %s, id, 'sms', phone, 'pending'
            FROM mm_users WHERE is_active=true AND phone_verified=true
            ON CONFLICT (signal_id, user_id, channel) DO NOTHING
        """, (signal_id,))
        conn.execute("""
            INSERT INTO mm_notification_deliveries(signal_id, user_id, channel, destination, status)
            SELECT %s, id, 'whatsapp', phone, 'pending'
            FROM mm_users WHERE is_active=true AND phone_verified=true
            ON CONFLICT (signal_id, user_id, channel) DO NOTHING
        """, (signal_id,))

    with get_db_connection() as conn:
        deliveries = conn.execute("""
            SELECT id, channel, destination
            FROM mm_notification_deliveries
            WHERE signal_id=%s AND status IN ('pending','retry')
              AND next_attempt_at <= NOW()
            ORDER BY id
        """, (signal_id,)).fetchall()

    for item in deliveries:
        try:
            if item["channel"] == "email":
                _smtp_send(item["destination"], "MarketMind AI — New signal", body)
            else:
                send_twilio_message(item["destination"], body, item["channel"])
            with get_db_connection() as conn:
                conn.execute("""
                    UPDATE mm_notification_deliveries
                    SET status='sent', sent_at=NOW(), last_error=NULL
                    WHERE id=%s
                """, (item["id"],))
        except Exception as exc:
            log.exception("Notification delivery failed: %s", item["id"])
            with get_db_connection() as conn:
                conn.execute("""
                    UPDATE mm_notification_deliveries
                    SET status='retry', attempts=attempts+1, last_error=%s,
                        next_attempt_at=NOW() + INTERVAL '2 minutes'
                    WHERE id=%s
                """, (str(exc)[:1000], item["id"]))

    with get_db_connection() as conn:
        remaining = conn.execute("""
            SELECT COUNT(*) AS n FROM mm_notification_deliveries
            WHERE signal_id=%s AND status IN ('pending','retry')
        """, (signal_id,)).fetchone()["n"]
        conn.execute("""
            UPDATE mm_signal_outbox SET status=%s,
                next_attempt_at=CASE WHEN %s=0 THEN NOW() ELSE NOW() + INTERVAL '2 minutes' END,
                completed_at=CASE WHEN %s=0 THEN NOW() ELSE completed_at END
            WHERE signal_id=%s
        """, ("sent" if remaining == 0 else "retry", remaining, remaining, signal_id))
    return True

class NotificationWorker:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="mm-notifications", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _run(self):
        while not self._stop.is_set():
            try:
                worked = _deliver_one()
            except Exception:
                log.exception("Notification worker cycle failed")
                worked = False
            self._stop.wait(3 if worked else 8)

notification_worker = NotificationWorker()
