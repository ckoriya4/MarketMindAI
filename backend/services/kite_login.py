
"""
MarketMind AI - Production Zerodha Kite Authentication

Flow:
1. Frontend redirects user to /api/auth/kite/login
2. User authenticates with Zerodha
3. Zerodha redirects to /api/auth/kite/callback
4. Backend exchanges request_token for access_token
5. Shared KiteClientManager is updated
6. Kite WebSocket is restarted
7. User is redirected to the Vercel frontend
"""

import os
import time
import secrets
import threading

from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from dotenv import load_dotenv
from kiteconnect import KiteConnect
from kiteconnect.exceptions import TokenException


# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------

BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

ENV_FILE = os.path.join(BASE, ".env")

load_dotenv(ENV_FILE, override=False)


# ---------------------------------------------------------
# EXISTING MARKETMIND SERVICES
# ---------------------------------------------------------

from .kite_client import kite_manager


# ---------------------------------------------------------
# ROUTER AND STATE
# ---------------------------------------------------------

router = APIRouter()

lock = threading.RLock()

pending = {}
cached = {}

COOKIE = "kite_login_state"

LOGIN_TIMEOUT = 600


# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------

def config():

    load_dotenv(ENV_FILE, override=False)

    api_key = os.getenv(
        "KITE_API_KEY", ""
    ).strip()

    api_secret = os.getenv(
        "KITE_API_SECRET", ""
    ).strip()

    frontend_url = os.getenv(
        "FRONTEND_URL", ""
    ).strip().rstrip("/")

    if not api_key or not api_secret:

        raise HTTPException(
            status_code=503,
            detail=(
                "KITE_API_KEY and KITE_API_SECRET "
                "must be configured in Render Environment."
            )
        )

    if not frontend_url:

        raise HTTPException(
            status_code=503,
            detail=(
                "FRONTEND_URL is missing. "
                "Set it to your deployed Vercel frontend URL."
            )
        )

    parsed = urlparse(frontend_url)

    if (
        parsed.scheme not in ("https", "http")
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):

        raise HTTPException(
            status_code=503,
            detail="Invalid FRONTEND_URL configuration."
        )

    return api_key, api_secret, frontend_url


# ---------------------------------------------------------
# RESPONSE SECURITY
# ---------------------------------------------------------

def clean(response):

    response.headers["Cache-Control"] = "no-store"

    response.headers["Pragma"] = "no-cache"

    response.headers["Referrer-Policy"] = "no-referrer"

    return response


def finish(message):

    _, _, frontend_url = config()

    destination = (
        frontend_url
        + "/?"
        + urlencode({"kite_login": message})
    )

    response = RedirectResponse(
        destination,
        status_code=303
    )

    response.delete_cookie(
        COOKIE,
        path="/api/auth/kite"
    )

    return clean(response)


def json_response(data):

    return clean(JSONResponse(data))


# ---------------------------------------------------------
# PENDING LOGIN CLEANUP
# ---------------------------------------------------------

def cleanup_pending():

    now = time.monotonic()

    for state, created in list(pending.items()):

        if now - created > LOGIN_TIMEOUT:

            pending.pop(state, None)


# ---------------------------------------------------------
# KITE LOGIN
# ---------------------------------------------------------

@router.get("/api/auth/kite/login")
def login(request: Request):

    api_key, _, _ = config()

    state = secrets.token_urlsafe(32)

    with lock:

        cleanup_pending()

        if len(pending) >= 100:

            raise HTTPException(
                status_code=429,
                detail="Too many pending login attempts."
            )

        pending[state] = time.monotonic()

    # Official Kite Connect login URL.
    query = urlencode({
        "v": 3,
        "api_key": api_key,
        "redirect_params": urlencode({
            "state": state
        })
    })

    login_url = (
        "https://kite.zerodha.com/connect/login?"
        + query
    )

    response = RedirectResponse(
        login_url,
        status_code=303
    )

    is_production = (
        os.getenv("ENVIRONMENT", "").lower()
        == "production"
    )

    response.set_cookie(
        key=COOKIE,
        value=state,
        max_age=LOGIN_TIMEOUT,
        httponly=True,
        secure=is_production,
        samesite="lax",
        path="/api/auth/kite"
    )

    return clean(response)


# ---------------------------------------------------------
# KITE CALLBACK
# ---------------------------------------------------------

@router.get("/api/auth/kite/callback")
def callback(request: Request):

    params = dict(request.query_params)

    # Avoid exposing request_token in ordinary access logs
    # where supported by the ASGI server.
    request.scope["query_string"] = b""

    state = params.get("state", "")

    cookie_state = request.cookies.get(
        COOKIE, ""
    )

    if (
        not state
        or not cookie_state
        or not secrets.compare_digest(
            state,
            cookie_state
        )
    ):

        return finish("invalid_state")

    with lock:

        cleanup_pending()

        created = pending.pop(state, None)

    if created is None:

        return finish("expired_login")

    if time.monotonic() - created > LOGIN_TIMEOUT:

        return finish("expired_login")

    request_token = params.get(
        "request_token", ""
    )

    status = params.get("status", "")

    if (
        status != "success"
        or not request_token
        or len(request_token) > 512
    ):

        return finish("cancelled")

    try:

        api_key, api_secret, _ = config()

        kite = KiteConnect(
            api_key=api_key,
            timeout=15
        )

        # Exchange one-time request token.
        session = kite.generate_session(
            request_token,
            api_secret=api_secret
        )

        access_token = session.get(
            "access_token", ""
        )

        if (
            not isinstance(access_token, str)
            or not access_token.strip()
        ):

            raise ValueError(
                "Kite did not return an access token."
            )

        # Verify token and activate shared client.
        success = kite_manager.set_access_token(
            access_token
        )

        if not success:

            return finish("exchange_failed")

        # -------------------------------------------------
        # RECONNECT KITE WEBSOCKET
        # -------------------------------------------------

        try:

            from .kite_stream import kite_stream

            try:
                kite_stream.stop()
            except Exception:
                pass

            kite_stream.start(
                kite_manager.api_key,
                kite_manager.access_token
            )

            print(
                "[KiteLogin] WebSocket restart requested."
            )

        except Exception as exc:

            # Authentication succeeded even if WebSocket
            # startup needs separate troubleshooting.
            print(
                "[KiteLogin] WebSocket restart warning:",
                str(exc)
            )

        # Invalidate cached status.
        with lock:
            cached.clear()

        print(
            "[KiteLogin] Zerodha authentication successful."
        )

        return finish("success")

    except TokenException:

        print("[KiteLogin] Kite token exchange rejected.")

        return finish("exchange_failed")

    except Exception as exc:

        print(
            "[KiteLogin] Authentication error:",
            str(exc)
        )

        return finish("exchange_failed")


# ---------------------------------------------------------
# KITE LOGIN STATUS
# ---------------------------------------------------------

@router.get("/api/auth/kite/status")
def status(request: Request):

    try:

        api_key, _, _ = config()

    except HTTPException:

        return json_response({
            "state": "setup_required"
        })

    # Use the shared manager instead of a separate
    # environment-only token check.
    manager_status = kite_manager.get_status()

    if not manager_status["has_access_token"]:

        return json_response({
            "state": "login_required",
            "connected": False
        })

    if manager_status["is_connected"]:

        return json_response({
            "state": "connected",
            "connected": True
        })

    return json_response({
        "state": "login_required",
        "connected": False
    })


# ---------------------------------------------------------
# OPTIONAL LOGOUT STATUS ENDPOINT
# ---------------------------------------------------------

@router.post("/api/auth/kite/logout")
def logout():

    with kite_manager._lock:

        kite_manager.kite = None
        kite_manager.access_token = ""
        kite_manager.is_connected = False

    os.environ.pop(
        "KITE_ACCESS_TOKEN",
        None
    )

    with lock:
        cached.clear()

    return json_response({
        "state": "logged_out",
        "connected": False
    })
