
import logging
import secrets

import psycopg
from psycopg.errors import UniqueViolation

from fastapi import APIRouter, Depends, Header, HTTPException

from ..services.database import get_db_connection
from ..services.notification_service import (
    send_email_otp,
    send_twilio_verification,
    verify_twilio_code,
)

from .schemas import (
    RegisterRequest,
    VerifyRegistrationRequest,
    LoginRequest,
)

from .security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
    make_otp,
    otp_digest,
    utc_now,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"],
)


# =========================================================
# CURRENT USER
# =========================================================

def current_user(
    authorization: str = Header(default="")
):

    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required."
        )

    token = authorization[7:].strip()

    try:
        user_id = decode_access_token(token)

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Session expired. Please log in again."
        ) from None

    try:

        with get_db_connection() as conn:

            user = conn.execute(
                """
                SELECT
                    id,
                    full_name,
                    email,
                    phone,
                    email_verified,
                    phone_verified
                FROM mm_users
                WHERE id = %s
                  AND is_active = TRUE
                """,
                (user_id,)
            ).fetchone()

    except Exception:
        logger.exception("Database error while loading current user")

        raise HTTPException(
            status_code=503,
            detail="Unable to verify user session. Please try again."
        ) from None

    if not user:
        raise HTTPException(
            status_code=401,
            detail="User account is unavailable."
        )

    return user


# =========================================================
# REGISTER
# =========================================================

@router.post("/register")
def register(data: RegisterRequest):

    email = str(data.email).lower().strip()
    phone = data.phone.strip()
    full_name = data.full_name.strip()

    if not full_name:
        raise HTTPException(
            status_code=422,
            detail="Full name is required."
        )

    if data.verify_via not in ("email", "phone"):
        raise HTTPException(
            status_code=422,
            detail="Verification method must be email or phone."
        )

    # -----------------------------------------------------
    # CHECK EXISTING USER
    # -----------------------------------------------------

    try:

        with get_db_connection() as conn:

            existing = conn.execute(
                """
                SELECT id
                FROM mm_users
                WHERE lower(email) = lower(%s)
                   OR phone = %s
                LIMIT 1
                """,
                (email, phone)
            ).fetchone()

            if existing:
                raise HTTPException(
                    status_code=409,
                    detail="Email or phone number is already registered."
                )

            # -------------------------------------------------
            # CREATE USER
            # -------------------------------------------------

            password_hash = hash_password(data.password)

            row = conn.execute(
                """
                INSERT INTO mm_users (
                    full_name,
                    email,
                    phone,
                    password_hash,
                    email_verified,
                    phone_verified,
                    is_active,
                    created_at
                )
                VALUES (
                    %s, %s, %s, %s,
                    FALSE, FALSE, TRUE, NOW()
                )
                RETURNING id
                """,
                (
                    full_name,
                    email,
                    phone,
                    password_hash
                )
            ).fetchone()

            user_id = row["id"]

            # -------------------------------------------------
            # CREATE OTP
            # -------------------------------------------------

            otp = make_otp()
            salt = secrets.token_hex(16)

            conn.execute(
                """
                INSERT INTO mm_auth_otps (
                    user_id,
                    purpose,
                    channel,
                    otp_hash,
                    salt,
                    expires_at,
                    attempts,
                    created_at
                )
                VALUES (
                    %s,
                    'register',
                    %s,
                    %s,
                    %s,
                    NOW() + INTERVAL '10 minutes',
                    0,
                    NOW()
                )
                """,
                (
                    user_id,
                    data.verify_via,
                    otp_digest(otp, salt),
                    salt
                )
            )

    except HTTPException:
        raise

    except UniqueViolation:
        logger.warning(
            "Registration rejected because email or phone already exists: %s",
            email
        )

        raise HTTPException(
            status_code=409,
            detail="Email or phone number is already registered."
        ) from None

    except Exception:
        logger.exception(
            "Registration database operation failed for email: %s",
            email
        )

        raise HTTPException(
            status_code=500,
            detail="Registration database operation failed. Check backend logs."
        ) from None

    # -----------------------------------------------------
    # SEND VERIFICATION CODE
    # -----------------------------------------------------

    try:

        if data.verify_via == "email":

            send_email_otp(
                email,
                otp
            )

        else:

            send_twilio_verification(
                phone,
                otp
            )

    except Exception:

        logger.exception(
            "OTP delivery failed for user ID: %s",
            user_id
        )

        # Clean up unverified registration.
        try:

            with get_db_connection() as conn:

                conn.execute(
                    """
                    DELETE FROM mm_users
                    WHERE id = %s
                      AND email_verified = FALSE
                      AND phone_verified = FALSE
                    """,
                    (user_id,)
                )

        except Exception:
            logger.exception(
                "Failed to clean up pending registration: %s",
                user_id
            )

        raise HTTPException(
            status_code=503,
            detail="Could not send verification code. Check email or Twilio configuration."
        ) from None

    return {
        "message": "Verification code sent.",
        "verification_method": data.verify_via,
    }


# =========================================================
# VERIFY REGISTRATION
# =========================================================

@router.post("/verify")
def verify_registration(data: VerifyRegistrationRequest):

    email = str(data.email).lower().strip()

    try:

        with get_db_connection() as conn:

            row = conn.execute(
                """
                SELECT
                    u.id,
                    u.phone,
                    o.channel,
                    o.otp_hash,
                    o.salt,
                    o.expires_at,
                    o.attempts
                FROM mm_users u
                JOIN mm_auth_otps o
                    ON o.user_id = u.id
                WHERE lower(u.email) = lower(%s)
                  AND o.purpose = 'register'
                ORDER BY o.created_at DESC
                LIMIT 1
                """,
                (email,)
            ).fetchone()

    except Exception:

        logger.exception(
            "Database error while loading registration OTP"
        )

        raise HTTPException(
            status_code=503,
            detail="Unable to access verification records."
        ) from None

    if not row:

        raise HTTPException(
            status_code=400,
            detail="No pending registration found."
        )

    if row["attempts"] >= 5:

        raise HTTPException(
            status_code=429,
            detail="Too many incorrect attempts. Request a new code."
        )

    # -----------------------------------------------------
    # VERIFY OTP
    # -----------------------------------------------------

    valid = False

    if row["channel"] == "email":

        valid = (
            row["expires_at"] > utc_now()
            and secrets.compare_digest(
                otp_digest(data.otp, row["salt"]),
                row["otp_hash"]
            )
        )

    else:

        try:

            valid = (
                row["expires_at"] > utc_now()
                and verify_twilio_code(
                    row["phone"],
                    data.otp
                )
            )

        except Exception:

            logger.exception(
                "Twilio verification failed for user ID: %s",
                row["id"]
            )

            raise HTTPException(
                status_code=503,
                detail="Twilio verification service unavailable."
            ) from None

    if not valid:

        try:

            with get_db_connection() as conn:

                conn.execute(
                    """
                    UPDATE mm_auth_otps
                    SET attempts = attempts + 1
                    WHERE user_id = %s
                      AND purpose = 'register'
                    """,
                    (row["id"],)
                )

        except Exception:

            logger.exception(
                "Failed to update OTP attempt count"
            )

        raise HTTPException(
            status_code=400,
            detail="Invalid or expired verification code."
        )

    # -----------------------------------------------------
    # ACTIVATE VERIFIED USER
    # -----------------------------------------------------

    try:

        with get_db_connection() as conn:

            if row["channel"] == "email":

                conn.execute(
                    """
                    UPDATE mm_users
                    SET email_verified = TRUE
                    WHERE id = %s
                    """,
                    (row["id"],)
                )

            else:

                conn.execute(
                    """
                    UPDATE mm_users
                    SET phone_verified = TRUE
                    WHERE id = %s
                    """,
                    (row["id"],)
                )

            conn.execute(
                """
                DELETE FROM mm_auth_otps
                WHERE user_id = %s
                  AND purpose = 'register'
                """,
                (row["id"],)
            )

            user = conn.execute(
                """
                SELECT
                    id,
                    full_name,
                    email,
                    phone,
                    email_verified,
                    phone_verified
                FROM mm_users
                WHERE id = %s
                """,
                (row["id"],)
            ).fetchone()

    except Exception:

        logger.exception(
            "Failed to activate verified user: %s",
            row["id"]
        )

        raise HTTPException(
            status_code=503,
            detail="Could not complete registration."
        ) from None

    if not user:

        raise HTTPException(
            status_code=500,
            detail="User record not found after verification."
        )

    return {
        "access_token": create_access_token(user["id"]),
        "token_type": "bearer",
        "user": user,
    }


# =========================================================
# LOGIN
# =========================================================

@router.post("/login")
def login(data: LoginRequest):

    identifier = data.identifier.strip()

    try:

        with get_db_connection() as conn:

            user = conn.execute(
                """
                SELECT
                    id,
                    full_name,
                    email,
                    phone,
                    password_hash,
                    email_verified,
                    phone_verified,
                    is_active
                FROM mm_users
                WHERE lower(email) = lower(%s)
                   OR phone = %s
                LIMIT 1
                """,
                (
                    identifier,
                    identifier
                )
            ).fetchone()

    except Exception:

        logger.exception(
            "Login database lookup failed"
        )

        raise HTTPException(
            status_code=503,
            detail="Login service temporarily unavailable."
        ) from None

    if (
        not user
        or not user["is_active"]
        or not verify_password(
            data.password,
            user["password_hash"]
        )
    ):

        raise HTTPException(
            status_code=401,
            detail="Invalid email/phone or password."
        )

    if not (
        user["email_verified"]
        or user["phone_verified"]
    ):

        raise HTTPException(
            status_code=403,
            detail="Please verify your email or phone before logging in."
        )

    public_user = {
        key: user[key]
        for key in (
            "id",
            "full_name",
            "email",
            "phone",
            "email_verified",
            "phone_verified",
        )
    }

    return {
        "access_token": create_access_token(user["id"]),
        "token_type": "bearer",
        "user": public_user,
    }


# =========================================================
# GET CURRENT USER
# =========================================================

@router.get("/me")
def me(user=Depends(current_user)):

    return {
        "user": user
    }


# =========================================================
# LOGOUT
# =========================================================

@router.post("/logout")
def logout(user=Depends(current_user)):

    # JWT is stateless.
    # Frontend should remove the saved access token.

    return {
        "message": "Logged out."
    }
