
import os
import json
import threading
import logging

import requests

from .database import get_db_connection


log = logging.getLogger("marketmind.notifications")


# =========================================================
# RESEND EMAIL API
# =========================================================

RESEND_API_URL = "https://api.resend.com/emails"


def _resend_send(to_email: str, subject: str, body: str):
    """
    Send email using Resend HTTP API.
    Gmail SMTP is not used.
    """

    api_key = os.getenv("RESEND_API_KEY", "").strip()
    sender = os.getenv("RESEND_FROM_EMAIL", "").strip()

    if not api_key:
        raise RuntimeError("RESEND_API_KEY is missing.")

    if not sender:
        raise RuntimeError(
            "RESEND_FROM_EMAIL is missing. "
            "Example: MarketMind AI <noreply@yourdomain.com>"
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }

    try:
        response = requests.post(
            RESEND_API_URL,
            headers=headers,
            json=payload,
            timeout=30,
        )

        if not response.ok:
            log.error(
                "Resend email failed. Status=%s Response=%s",
                response.status_code,
                response.text[:1000],
            )

        response.raise_for_status()

        result = response.json()

        log.info(
            "Email successfully sent using Resend. "
            "Recipient=%s EmailID=%s",
            to_email,
            result.get("id"),
        )

        return result.get("id")

    except requests.RequestException:
        log.exception(
            "Resend email delivery failed. Recipient=%s",
            to_email,
        )
        raise


# =========================================================
# REGISTRATION EMAIL OTP
# =========================================================

def send_email_otp(to_email: str, otp: str):
    body = (
        "Hello,\n\n"
        "Your MarketMind AI verification code is:\n\n"
        f"{otp}\n\n"
        "This OTP expires in 10 minutes.\n"
        "Do not share this code with anyone.\n\n"
        "Regards,\n"
        "MarketMind AI"
    )

    return _resend_send(
        to_email,
        "MarketMind AI - Email Verification",
        body,
    )


# =========================================================
# TWILIO COMPATIBILITY FUNCTIONS
# Registration and notifications currently use EMAIL ONLY.
# These functions are retained in case another module imports them.
# They are intentionally disabled.
# =========================================================

def send_twilio_verification(phone: str, otp: str):
    raise RuntimeError(
        "Phone OTP verification is currently disabled. "
        "Only email verification is enabled."
    )


def verify_twilio_code(phone: str, otp: str) -> bool:
    raise RuntimeError(
        "Phone OTP verification is currently disabled. "
        "Only email verification is enabled."
    )


def send_twilio_message(to: str, body: str, channel: str):
    raise RuntimeError(
        "SMS and WhatsApp notifications are currently disabled. "
        "Only email notifications are enabled."
    )


# =========================================================
# SIGNAL MESSAGE
# =========================================================

def _signal_message(signal):
    fields = [
        "MarketMind AI - New Signal",
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
        "Educational signal only; not investment advice.",
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
                json.dumps(signal, default=str),
            ),
        )


# =========================================================
# PROCESS ONE SIGNAL
# EMAIL ONLY
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
            (event["signal_id"],),
        )

        payload = event["payload"]
        signal_id = event["signal_id"]

    body = _signal_message(payload)

    # -----------------------------------------------------
    # CREATE EMAIL DELIVERY ROWS ONLY
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
            (signal_id,),
        )

    # -----------------------------------------------------
    # LOAD PENDING EMAIL DELIVERIES
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
              AND channel = 'email'
              AND status IN ('pending', 'retry')
              AND next_attempt_at <= NOW()
            ORDER BY id
            """,
            (signal_id,),
        ).fetchall()

    # -----------------------------------------------------
    # SEND EMAIL NOTIFICATIONS
    # -----------------------------------------------------

    for item in deliveries:

        try:

            _resend_send(
                item["destination"],
                "MarketMind AI - New Signal",
                body,
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
                    (item["id"],),
                )

        except Exception as exc:

            log.exception(
                "Email notification delivery failed: %s",
                item["id"],
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
                        item["id"],
                    ),
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
              AND channel = 'email'
              AND status IN ('pending', 'retry')
            """,
            (signal_id,),
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
                signal_id,
            ),
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
            daemon=True,
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
