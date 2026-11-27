import os
import secrets
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg.errors import UniqueViolation

from ..services.database import get_db_connection
from ..services.notification_service import (
    send_email_otp, send_twilio_verification, verify_twilio_code
)
from .schemas import RegisterRequest, VerifyRegistrationRequest, LoginRequest, ResendOtpRequest
from .security import (
    create_access_token, decode_access_token, hash_password, verify_password,
    make_otp, otp_digest, utc_now
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

def current_user(authorization: str = Header(default="")):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required.")
    try:
        user_id = decode_access_token(authorization[7:].strip())
    except Exception:
        raise HTTPException(401, "Session expired. Please log in again.") from None
    with get_db_connection() as conn:
        user = conn.execute("""
            SELECT id, full_name, email, phone, email_verified, phone_verified
            FROM mm_users WHERE id=%s AND is_active=true
        """, (user_id,)).fetchone()
    if not user:
        raise HTTPException(401, "User account is unavailable.")
    return user

@router.post("/register")
def register(data: RegisterRequest):
    email = str(data.email).lower().strip()
    with get_db_connection() as conn:
        existing = conn.execute("""
            SELECT id FROM mm_users WHERE lower(email)=lower(%s) OR phone=%s
        """, (email, data.phone)).fetchone()
        if existing:
            raise HTTPException(409, "Email or phone number is already registered.")
        row = conn.execute("""
            INSERT INTO mm_users(full_name,email,phone,password_hash,email_verified,phone_verified,is_active,created_at)
            VALUES (%s,%s,%s,%s,false,false,true,NOW())
            RETURNING id
        """, (data.full_name.strip(), email, data.phone, hash_password(data.password))).fetchone()
        user_id = row["id"]
        otp = make_otp()
        salt = secrets.token_hex(16)
        conn.execute("""
            INSERT INTO mm_auth_otps(user_id, purpose, channel, otp_hash, salt, expires_at, created_at)
            VALUES (%s,'register',%s,%s,%s,NOW() + INTERVAL '10 minutes',NOW())
        """, (user_id, data.verify_via, otp_digest(otp, salt), salt))
    try:
        if data.verify_via == "email":
            send_email_otp(email, otp)
        else:
            send_twilio_verification(data.phone, otp)
    except Exception as exc:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM mm_users WHERE id=%s AND email_verified=false AND phone_verified=false", (user_id,))
        raise HTTPException(503, f"Could not send verification code. Check provider configuration: {str(exc)[:180]}") from None
    return {"message": "Verification code sent.", "verification_method": data.verify_via}

@router.post("/verify")
def verify_registration(data: VerifyRegistrationRequest):
    email = str(data.email).lower().strip()
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT u.id,u.phone,o.channel,o.otp_hash,o.salt,o.expires_at,o.attempts
            FROM mm_users u
            JOIN mm_auth_otps o ON o.user_id=u.id
            WHERE lower(u.email)=lower(%s) AND o.purpose='register'
            ORDER BY o.created_at DESC LIMIT 1
        """, (email,)).fetchone()
    if not row:
        raise HTTPException(400, "No pending registration found.")
    if row["attempts"] >= 5:
        raise HTTPException(429, "Too many incorrect attempts. Request a new code.")
    valid = False
    if row["channel"] == "email":
        valid = row["expires_at"] > utc_now() and secrets.compare_digest(
            otp_digest(data.otp, row["salt"]), row["otp_hash"]
        )
    else:
        try:
            valid = verify_twilio_code(row["phone"], data.otp)
        except Exception:
            raise HTTPException(503, "Twilio verification service unavailable.") from None
    if not valid:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE mm_auth_otps SET attempts=attempts+1
                WHERE user_id=%s AND purpose='register'
            """, (row["id"],))
        raise HTTPException(400, "Invalid or expired verification code.")
    with get_db_connection() as conn:
        if row["channel"] == "email":
            conn.execute("UPDATE mm_users SET email_verified=true WHERE id=%s", (row["id"],))
        else:
            conn.execute("UPDATE mm_users SET phone_verified=true WHERE id=%s", (row["id"],))
        conn.execute("DELETE FROM mm_auth_otps WHERE user_id=%s AND purpose='register'", (row["id"],))
        user = conn.execute("""
            SELECT id,full_name,email,phone,email_verified,phone_verified
            FROM mm_users WHERE id=%s
        """, (row["id"],)).fetchone()
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer", "user": user}

@router.post("/login")
def login(data: LoginRequest):
    identifier = data.identifier.strip()
    with get_db_connection() as conn:
        user = conn.execute("""
            SELECT id,full_name,email,phone,password_hash,email_verified,phone_verified,is_active
            FROM mm_users
            WHERE lower(email)=lower(%s) OR phone=%s
            LIMIT 1
        """, (identifier, identifier)).fetchone()
    if not user or not user["is_active"] or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email/phone or password.")
    if not (user["email_verified"] or user["phone_verified"]):
        raise HTTPException(403, "Please verify your email or phone before logging in.")
    public_user = {k: user[k] for k in ("id","full_name","email","phone","email_verified","phone_verified")}
    return {"access_token": create_access_token(user["id"]), "token_type": "bearer", "user": public_user}

@router.get("/me")
def me(user=Depends(current_user)):
    return {"user": user}

@router.post("/logout")
def logout(user=Depends(current_user)):
    # JWT is stateless; client removes its token. Token expiry bounds the session.
    return {"message": "Logged out."}
