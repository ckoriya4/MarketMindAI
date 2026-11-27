import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "720"))

def _require_secret():
    if len(JWT_SECRET) < 32:
        raise RuntimeError("JWT_SECRET must be set to a random value of at least 32 characters.")

def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return "scrypt${}${}${}".format(
        salt.hex(), digest.hex(), "16384"
    )

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_hex, digest_hex, _n = encoded.split("$", 3)
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def create_access_token(user_id: int) -> str:
    _require_secret()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "iss": "marketmind-ai",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> int:
    _require_secret()
    payload = jwt.decode(
        token, JWT_SECRET, algorithms=[JWT_ALGORITHM], issuer="marketmind-ai"
    )
    return int(payload["sub"])

def make_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

def otp_digest(otp: str, salt: str) -> str:
    key = os.getenv("OTP_PEPPER", JWT_SECRET).encode("utf-8")
    return hmac.new(key, f"{salt}:{otp}".encode("utf-8"), hashlib.sha256).hexdigest()

def utc_now():
    return datetime.now(timezone.utc)
