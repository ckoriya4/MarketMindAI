
import os
import ssl
import json
import smtplib
import threading
import logging
from email.message import EmailMessage

import requests

from .database import get_db_connection


log = logging.getLogger("marketmind.notifications")


# =========================================================
# EMAIL SMTP
# =========================================================

def _smtp_send(to_email: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    user = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    sender = os.getenv("SMTP_FROM", user).strip()

    if not all([host, user, password, sender]):
        raise RuntimeError(
            "SMTP configuration missing. "
            "Required: SMTP_HOST, SMTP_USERNAME, "
            "SMTP_PASSWORD, SMTP_FROM."
        )

    port = int(os.getenv("SMTP_PORT", "465"))
    timeout = int(os.getenv("SMTP_TIMEOUT", "30"))

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = to_email
    message.set_content(body)

    try:
        if port == 465:
            # Gmail SSL connection
            context = ssl.create_default_context()

            with smtplib.SMTP_SSL(
                host,
                port,
                timeout=timeout,
                context=context
            ) as server:

                server.login(user, password)
                server.send_message(message)

        else:
            # STARTTLS connection, normally port 587
            with smtplib.SMTP(
                host,
                port,
                timeout=timeout
            ) as server:

                server.ehlo()
                server.starttls(
                    context=ssl.create_default_context()
                )
                server.ehlo()
                server.login(user, password)
                server.send_message(message)

        log.info(
            "Email successfully sent to %s",
            to_email
        )

    except Exception:
        log.exception(
            "SMTP email delivery failed. Host=%s Port=%s Recipient=%s",
            host,
            port,
            to_email
        )
        raise


def send_email_otp(to_email: str, otp: str):
    body = (
        "Your MarketMind AI verification code is "
        f"{otp}.\n\n"
        "It expires in 10 minutes.\n"
        "Do not share this code with anyone."
    )

    _smtp_send(
        to_email,
        "MarketMind AI verification code",
        body
    )


# =========================================================
# TWILIO VERIFY - REGISTRATION OTP
# =========================================================

def _get_twilio_verify_config():
    account = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    service = os.getenv(
        "TWILIO_VERIFY_SERVICE_SID", ""
    ).strip()

    if not all([account, token, service]):
        raise RuntimeError(
            "Twilio Verify configuration missing. "
            "Required: TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, "
            "TWILIO_VERIFY_SERVICE_SID."
        )

    return account, token, service


def send_twilio_verification(phone: str, otp: str):
    account, token, service = _get_twilio_verify_config()

    channel = (
        "whatsapp"
        if os.getenv(
            "TWILIO_VERIFY_WHATSAPP", "false"
        ).lower() == "true"
        else "sms"
    )

    url = (
        f"https://verify.twilio.com/v2/Services/"
        f"{service}/Verifications"
    )

    try:
        response = requests.post(
            url,
            auth=(account, token),
            data={
                "To": phone,
                "Channel": channel
            },
            timeout=30
        )

        if not response.ok:
            log.error(
                "Twilio OTP request failed. "
                "Status=%s Response=%s",
                response.status_code,
                response.text[:1000]
            )

        response.raise_for_status()

        log.info(
            "Twilio verification initiated for %s via %s",
            phone,
            channel
        )

    except requests.RequestException:
        log.exception(
            "Twilio verification request failed for %s",
            phone
        )
        raise


def verify_twilio_code(phone: str, otp: str) -> bool:
    account, token, service = _get_twilio_verify_config()

    url = (
        f"https://verify.twilio.com/v2/Services/"
        f"{service}/VerificationCheck"
    )

    try:
        response = requests.post(
            url,
            auth=(account, token),
            data={
                "To": phone,
                "Code": otp
            },
            timeout=30
        )

        if not response.ok:
            log.error(
                "Twilio verification check failed. "
                "Status=%s Response=%s",
                response.status_code,
                response.text[:1000]
            )

        response.raise_for_status()

        return (
            response.json().get("status") == "approved"
        )

    except requests.RequestException:
        log.exception(
            "Twilio OTP verification request failed for %s",
            phone
        )
        raise


# =========================================================
# TWILIO SMS / WHATSAPP SIGNAL NOTIFICATIONS
# =========================================================

def send_twilio_message(
    to: str,
    body: str,
    channel: str
):
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()

    if channel not in ("sms", "whatsapp"):
        raise ValueError(
            f"Unsupported Twilio channel: {channel}"
        )

    from_number = os.getenv(
        "TWILIO_WHATSAPP_FROM"
        if channel == "whatsapp"
        else "TWILIO_SMS_FROM",
        ""
    ).strip()

    if not all([sid, token, from_number]):
        raise RuntimeError(
            f"Twilio {channel} sender is not configured."
        )

    if channel == "whatsapp":
        if not from_number.startswith("whatsapp:"):
            from_number = "whatsapp:" + from_number

        if not to.startswith("whatsapp:"):
            to = "whatsapp:" + to

    url = (
        f"https://api.twilio.com/2010-04-01/"
        f"Accounts/{sid}/Messages.json"
    )

    data = {
        "From": from_number,
        "To": to
    }

    content_sid = (
        os.getenv("TWILIO_WHATSAPP_CONTENT_SID", "").strip()
        if channel == "whatsapp"
        else ""
    )

    if content_sid:
        data["ContentSid"] = content_sid
        data["ContentVariables"] = json.dumps({
            "1": body
        })
    else:
        data["Body"] = body

    try:
        response = requests.post(
            url,
            auth=(sid, token),
            data=data,
            timeout=30
        )

        if not response.ok:
            log.error(
                "Twilio message failed. "
                "Channel=%s Status=%s Response=%s",
                channel,
                response.status_code,
                response.text[:1000]
            )

        response.raise_for_status()

        result = response.json()

        log.info(
            "Twilio %s message sent. SID=%s",
            channel,
            result.get("sid")
        )

        return result.get("sid")

    except requests.RequestException:
        log.exception(
            "Twilio %s message delivery failed",
            channel
        )
        raise


# =========================================================
# SIGNAL MESSAGE
# =========================================================

def _signal_message(signal):
    fields = [
        "MarketMind AI — New Signal",
        f"Signal: {signal.get('action')}",
        f"Score: {signal.get('score')}%",
        f"Base Score: {signal.get('base_score')}%",
        f"Expiry: {signal.get('expiry')}",
        (
            f"Strike: {signal.get('strike')} "
            f"{signal.get('option_type')}"
        ),
        f"Symbol: {signal.get('trading_symbol')}",
        f"Initial LTP: {signal.get('initial_ltp')}",
        f"OI: {signal.get('oi')}",
        (
            f"OI Change: {signal.get('oi_change')} "
            f"({signal.get('oi_change_pct')}%)"
        ),
        f"Signal ID: {signal.get('unique_id')}",
        "Educational signal only; not investment advice."
    ]

    return "\n".join(str(x) for x in fields)


# =========================================================
# ADD SIGNAL TO OUTBOX
# =========================================================

def enqueue_signal_notification(signal: dict):
    """
    Persist one notification event after successful Excel write.
    Duplicate unique_id is ignored.
    """

    signal_id = str(signal["unique_id"])

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO mm_signal_outbox(
                signal_id,
                payload,
                status,
                created_at
            )
            VALUES (%s, %s::jsonb, 'pending', NOW())
            ON CONFLICT (signal_id) DO NOTHING
            """,
            (
                signal_id,
                json.dumps(signal, default=str)
            )
        )


# =========================================================
# PROCESS ONE SIGNAL
# =========================================================

def _deliver_one():

    with get_db_connection() as conn:

        event = conn.execute(
            """
            SELECT signal_id, payload
            FROM mm_signal_outbox
            WHERE (
                status IN ('pending', 'retry')
                AND next_attempt_at <= NOW()
            )
            OR (
                status = 'processing'
                AND created_at < NOW() - INTERVAL '5 minutes'
            )
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ).fetchone()

        if not event:
            return False

        conn.execute(
            """
            UPDATE mm_signal_outbox
            SET status = 'processing',
                attempts = attempts + 1
            WHERE signal_id = %s
            """,
            (event["signal_id"],)
        )

        payload = event["payload"]
        signal_id = event["signal_id"]

    body = _signal_message(payload)

    # -----------------------------------------------------
    # CREATE EMAIL DELIVERY ROWS
    # -----------------------------------------------------

    with get_db_connection() as conn:

        conn.execute(
            """
            INSERT INTO mm_notification_deliveries(
                signal_id,
                user_id,
                channel,
                destination,
                status
            )
            SELECT
                %s,
                id,
                'email',
                email,
                'pending'
            FROM mm_users
            WHERE is_active = TRUE
              AND email_verified = TRUE
            ON CONFLICT (
                signal_id,
                user_id,
                channel
            ) DO NOTHING
            """,
            (signal_id,)
        )

        # -------------------------------------------------
        # CREATE SMS DELIVERY ROWS
        # -------------------------------------------------

        conn.execute(
            """
            INSERT INTO mm_notification_deliveries(
                signal_id,
                user_id,
                channel,
                destination,
                status
            )
            SELECT
                %s,
                id,
                'sms',
                phone,
                'pending'
            FROM mm_users
            WHERE is_active = TRUE
              AND phone_verified = TRUE
            ON CONFLICT (
                signal_id,
                user_id,
                channel
            ) DO NOTHING
            """,
            (signal_id,)
        )

        # -------------------------------------------------
        # CREATE WHATSAPP DELIVERY ROWS
        # -------------------------------------------------

        conn.execute(
            """
            INSERT INTO mm_notification_deliveries(
                signal_id,
                user_id,
                channel,
                destination,
                status
            )
            SELECT
                %s,
                id,
                'whatsapp',
                phone,
                'pending'
            FROM mm_users
            WHERE is_active = TRUE
              AND phone_verified = TRUE
            ON CONFLICT (
                signal_id,
                user_id,
                channel
            ) DO NOTHING
            """,
            (signal_id,)
        )

    # -----------------------------------------------------
    # LOAD PENDING DELIVERIES
    # -----------------------------------------------------

    with get_db_connection() as conn:

        deliveries = conn.execute(
            """
            SELECT
                id,
                channel,
                destination
            FROM mm_notification_deliveries
            WHERE signal_id = %s
              AND status IN ('pending', 'retry')
              AND next_attempt_at <= NOW()
            ORDER BY id
            """,
            (signal_id,)
        ).fetchall()

    # -----------------------------------------------------
    # SEND NOTIFICATIONS
    # -----------------------------------------------------

    for item in deliveries:

        try:

            if item["channel"] == "email":

                _smtp_send(
                    item["destination"],
                    "MarketMind AI — New signal",
                    body
                )

            else:

                send_twilio_message(
                    item["destination"],
                    body,
                    item["channel"]
                )

            with get_db_connection() as conn:

                conn.execute(
                    """
                    UPDATE mm_notification_deliveries
                    SET status = 'sent',
                        sent_at = NOW(),
                        last_error = NULL
                    WHERE id = %s
                    """,
                    (item["id"],)
                )

        except Exception as exc:

            log.exception(
                "Notification delivery failed: %s",
                item["id"]
            )

            with get_db_connection() as conn:

                conn.execute(
                    """
                    UPDATE mm_notification_deliveries
                    SET status = 'retry',
                        attempts = attempts + 1,
                        last_error = %s,
                        next_attempt_at =
                            NOW() + INTERVAL '2 minutes'
                    WHERE id = %s
                    """,
                    (
                        str(exc)[:1000],
                        item["id"]
                    )
                )

    # -----------------------------------------------------
    # UPDATE SIGNAL STATUS
    # -----------------------------------------------------

    with get_db_connection() as conn:

        remaining = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM mm_notification_deliveries
            WHERE signal_id = %s
              AND status IN ('pending', 'retry')
            """,
            (signal_id,)
        ).fetchone()["n"]

        conn.execute(
            """
            UPDATE mm_signal_outbox
            SET status = %s,
                next_attempt_at = CASE
                    WHEN %s = 0 THEN NOW()
                    ELSE NOW() + INTERVAL '2 minutes'
                END,
                completed_at = CASE
                    WHEN %s = 0 THEN NOW()
                    ELSE completed_at
                END
            WHERE signal_id = %s
            """,
            (
                "sent" if remaining == 0 else "retry",
                remaining,
                remaining,
                signal_id
            )
        )

    return True


# =========================================================
# BACKGROUND NOTIFICATION WORKER
# =========================================================

class NotificationWorker:

    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):

        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()

        self._thread = threading.Thread(
            target=self._run,
            name="mm-notifications",
            daemon=True
        )

        self._thread.start()

        log.info("Notification worker started.")

    def stop(self):

        self._stop.set()

        if self._thread:
            self._thread.join(timeout=10)

        log.info("Notification worker stopped.")

    def _run(self):

        while not self._stop.is_set():

            try:
                worked = _deliver_one()

            except Exception:
                log.exception(
                    "Notification worker cycle failed"
                )
                worked = False

            self._stop.wait(
                3 if worked else 8
            )


notification_worker = NotificationWorker()
