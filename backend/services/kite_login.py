
"""
MarketMind AI - Zerodha Kite Authentication with PostgreSQL

Login flow:
1. Frontend opens /api/auth/kite/login
2. User authenticates with Zerodha
3. Zerodha redirects to /api/auth/kite/callback
4. Backend exchanges request_token for access_token
5. Shared KiteClientManager verifies and saves access_token in PostgreSQL
6. Kite WebSocket starts
7. User returns to the Vercel dashboard
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

from .kite_client import kite_manager


# --------------------------------------------------
# ENVIRONMENT
# --------------------------------------------------

BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

ENV_FILE = os.path.join(BASE, ".env")

load_dotenv(ENV_FILE, override=False)


# --------------------------------------------------
# ROUTER AND LOGIN STATE
# --------------------------------------------------

router = APIRouter()

lock = threading.RLock()

pending = {}

COOKIE = "kite_login_state"

LOGIN_TIMEOUT = 600


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

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
            detail="Kite API credentials are missing."
        )

    if not frontend_url:
        raise HTTPException(
            status_code=503,
            detail="FRONTEND_URL is missing."
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
            detail="Invalid FRONTEND_URL."
        )

    return api_key, api_secret, frontend_url


# --------------------------------------------------
# SECURITY HEADERS
# --------------------------------------------------

def clean(response):

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"

    return response


# --------------------------------------------------
# FRONTEND REDIRECT
# --------------------------------------------------

def finish(message):

    _, _, frontend_url = config()

    destination = (
        frontend_url
        + "/?"
        + urlencode({
            "kite_login": message
        })
    )

    response = RedirectResponse(
        destination,
        status_code=303
    )

    response.delete_cookie(
        key=COOKIE,
        path="/api/auth/kite"
    )

    return clean(response)


# --------------------------------------------------
# JSON RESPONSE
# --------------------------------------------------

def json_response(data, status_code=200):

    return clean(
        JSONResponse(
            data,
            status_code=status_code
        )
    )


# --------------------------------------------------
# CLEANUP EXPIRED LOGIN STATES
# --------------------------------------------------

def cleanup_pending():

    now = time.monotonic()

    for state, created in list(pending.items()):

        if now - created > LOGIN_TIMEOUT:
            pending.pop(state, None)


# --------------------------------------------------
# START KITE WEBSOCKET
# --------------------------------------------------

def start_kite_stream():

    if not kite_manager.is_connected:
        print("[KiteLogin] Cannot start WebSocket: Kite is disconnected.")
        return False

    try:

        from .kite_stream import kite_stream

        # Stop an old stream before starting a new one.
        kite_stream.stop()

        started = kite_stream.start(
            kite_manager.api_key,
            kite_manager.access_token
        )

        print(
            "[KiteLogin] WebSocket start requested:",
            bool(started)
        )

        return bool(started)

    except Exception as exc:

        print(
            "[KiteLogin] WebSocket startup error:",
            str(exc)
        )

        return False


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@router.get("/api/auth/kite/login")
def login(request: Request):

    api_key, _, frontend_url = config()

    state = secrets.token_urlsafe(32)

    with lock:

        cleanup_pending()

        if len(pending) >= 100:
            raise HTTPException(
                status_code=429,
                detail="Too many pending login attempts."
            )

        pending[state] = time.monotonic()

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

    # HTTPS in production; HTTP allowed for localhost testing.
    secure_cookie = frontend_url.startswith("https://")

    response.set_cookie(
        key=COOKIE,
        value=state,
        max_age=LOGIN_TIMEOUT,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        path="/api/auth/kite"
    )

    return clean(response)


# --------------------------------------------------
# CALLBACK
# --------------------------------------------------

@router.get("/api/auth/kite/callback")
def callback(request: Request):

    params = dict(request.query_params)

    state = params.get("state", "")

    cookie_state = request.cookies.get(
        COOKIE, ""
    )

    # Validate state against the browser cookie.
    if (
        not state
        or not cookie_state
        or not secrets.compare_digest(
            state,
            cookie_state
        )
    ):
        print("[KiteLogin] Invalid callback state.")
        return finish("invalid_state")

    # Validate that this login was initiated by this backend.
    with lock:

        cleanup_pending()

        created = pending.pop(
            state,
            None
        )

    if created is None:
        return finish("expired_login")

    if time.monotonic() - created > LOGIN_TIMEOUT:
        return finish("expired_login")

    request_token = params.get(
        "request_token", ""
    )

    login_status = params.get(
        "status", ""
    )

    if (
        login_status != "success"
        or not request_token
        or len(request_token) > 512
    ):
        return finish("cancelled")

    try:

        api_key, api_secret, _ = config()

        # Exchange request_token for access_token.
        kite = KiteConnect(
            api_key=api_key,
            timeout=15
        )

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

        # Verify token and save it to PostgreSQL.
        saved = kite_manager.set_access_token(
            access_token
        )

        if not saved:
            print(
                "[KiteLogin] Access token verification or PostgreSQL save failed."
            )
            return finish("exchange_failed")

        # Start WebSocket using the shared Kite manager.
        websocket_started = start_kite_stream()

        print("[KiteLogin] Authentication successful.")
        print(
            "[KiteLogin] WebSocket start requested:",
            websocket_started
        )

        # Authentication is successful even if the WebSocket
        # takes a little time to establish its connection.
        return finish("success")

    except TokenException:

        print(
            "[KiteLogin] Zerodha rejected the request token."
        )

        return finish("exchange_failed")

    except Exception as exc:

        print(
            "[KiteLogin] Callback error:",
            str(exc)
        )

        return finish("exchange_failed")


# --------------------------------------------------
# STATUS
# --------------------------------------------------

@router.get("/api/auth/kite/status")
def status(request: Request):

    try:
        config()

    except HTTPException:

        return json_response({
            "state": "setup_required",
            "connected": False,
            "websocket_connected": False
        })

    manager_status = kite_manager.get_status()

    if not manager_status["is_connected"]:

        return json_response({
            "state": "login_required",
            "connected": False,
            "websocket_connected": False
        })

    try:

        from .kite_stream import kite_stream

        websocket_connected = bool(
            kite_stream.connected
        )

    except Exception as exc:

        print(
            "[KiteLogin] WebSocket status error:",
            str(exc)
        )

        websocket_connected = False

    return json_response({
        "state": "connected",
        "connected": True,
        "websocket_connected": websocket_connected,
        "mode": manager_status["mode"],
        "user_id": manager_status.get("user_id")
    })


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@router.post("/api/auth/kite/logout")
def logout():

    # Stop the WebSocket first.
    try:

        from .kite_stream import kite_stream

        kite_stream.stop()

    except Exception as exc:

        print(
            "[KiteLogin] WebSocket stop warning:",
            str(exc)
        )

    # Delete the token from PostgreSQL.
    deleted = kite_manager.logout()

    if not deleted:

        return json_response({
            "state": "logout_failed",
            "connected": kite_manager.is_connected,
            "detail": "Could not delete the saved token from PostgreSQL."
        }, status_code=503)

    return json_response({
        "state": "logged_out",
        "connected": False,
        "websocket_connected": False
    })
