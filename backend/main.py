
"""MarketMind AI - Dashboard API with PostgreSQL-backed Kite authentication."""

import asyncio
import csv
import io
import os
import time

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Optional

import requests

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


from .services.option_chart_service import get_option_chart_data


# ---------------------------------------------------------
# ENVIRONMENT
# ---------------------------------------------------------

BASE = Path(__file__).resolve().parent

load_dotenv(BASE / ".env", override=False)


# ---------------------------------------------------------
# EXISTING SERVICES
# ---------------------------------------------------------

from .services.kite_client import kite_manager
from .services.kite_stream import kite_stream

from .services.option_chain import (
    get_dynamic_option_chain,
    get_upcoming_expiries
)

from .services.option_chain_history import (
    get_option_history_dates,
    get_historical_option_chain
)

from .services.chart_service import get_chart_data

from .services.oi_signal import router as oi_signal_router
from .services.confluence_service import router as confluence_router
from .services.energy_service import router as energy_router
from .services.market_overview import router as market_overview_router
from .services.sector_oi import router as sector_oi_router

from .services.session_recorder import recorder

from .services.stock_option_data import (
    collector as stock_oi_collector,
    scanner_quotes,
    configure_constituents
)

from .services.weighted_setup import router as weighted_setup_router
from .services.live_crude import router as live_crude_router
from .services.trade_setups import router as trade_setup_router
from .services.oi_percent_reference import router as oi_reference_router

from .services.direct_alerts import install_direct_alerts
from .services.kite_login import router as kite_login_router

from .auth.router import router as auth_router

from .services.trade_excel_recorder import (
    router as trade_excel_router,
    trade_excel_recorder,
)


# ---------------------------------------------------------
# CORS ORIGINS
# ---------------------------------------------------------

def get_allowed_origins():

    origins = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }

    frontend_url = os.getenv(
        "FRONTEND_URL",
        ""
    ).strip().rstrip("/")

    if frontend_url:
        origins.add(frontend_url)

    extra_origins = os.getenv(
        "FRONTEND_ORIGINS",
        ""
    )

    for origin in extra_origins.split(","):

        origin = origin.strip().rstrip("/")

        if origin:
            origins.add(origin)

    return sorted(origins)


# ---------------------------------------------------------
# APPLICATION LIFESPAN
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    print("[MarketMind] Starting dashboard services...")

    # Start existing OI session recorder.
    try:
        recorder.start()
        print("[MarketMind] OI session recorder started.")

    except Exception as exc:
        print(
            "[MarketMind] Recorder startup warning:",
            str(exc)
        )

    # Reload token from PostgreSQL and verify with Zerodha.
    try:

        restored = kite_manager.reconnect()

        if restored:

            print(
                "[MarketMind] PostgreSQL Kite session restored."
            )

            started = kite_stream.start(
                kite_manager.api_key,
                kite_manager.access_token
            )

            print(
                "[MarketMind] Kite WebSocket start requested:",
                started
            )

        else:

            print(
                "[MarketMind] No valid saved Kite session. "
                "Login with Kite is required."
            )

    except Exception as exc:

        print(
            "[MarketMind] Kite startup error:",
            str(exc)
        )

    # Start stock OI collector.
    try:

        stock_oi_collector.start()

        print(
            "[MarketMind] Stock OI collector started."
        )

    except Exception as exc:

        print(
            "[MarketMind] Stock OI collector startup warning:",
            str(exc)
        )

    # Start durable signal-notification delivery worker.
    try:

        from .services.notification_service import notification_worker

        notification_worker.start()

        print(
            "[MarketMind] Notification worker started."
        )

    except Exception as exc:

        print(
            "[MarketMind] Notification worker startup warning:",
            str(exc)
        )

    # Start background Excel signal recorder.
    try:

        trade_excel_recorder.start()

        print(
            "[MarketMind] Trade Excel recorder started."
        )

    except Exception as exc:

        print(
            "[MarketMind] Trade Excel recorder startup warning:",
            str(exc)
        )

    try:

        yield

    finally:

        print(
            "[MarketMind] Stopping dashboard services..."
        )

        # Stop notification delivery worker.
        try:

            from .services.notification_service import notification_worker

            await asyncio.to_thread(
                notification_worker.stop
            )

        except Exception as exc:

            print(
                "[MarketMind] Notification worker shutdown warning:",
                str(exc)
            )

        # Stop Excel recorder.
        try:

            await asyncio.to_thread(
                trade_excel_recorder.stop
            )

            print(
                "[MarketMind] Trade Excel recorder stopped."
            )

        except Exception as exc:

            print(
                "[MarketMind] Trade Excel recorder shutdown error:",
                str(exc)
            )

        # Stop Kite WebSocket.
        try:

            kite_stream.stop()

        except Exception as exc:

            print(
                "[KiteStream] Shutdown error:",
                str(exc)
            )

        # Stop stock OI collector.
        try:

            stock_oi_collector.stop()

        except Exception as exc:

            print(
                "[MarketMind] Collector shutdown error:",
                str(exc)
            )

        # Stop existing OI session recorder.
        try:

            await asyncio.to_thread(
                recorder.stop
            )

        except Exception as exc:

            print(
                "[MarketMind] Recorder shutdown error:",
                str(exc)
            )

        print(
            "[MarketMind] Dashboard stopped."
        )


# ---------------------------------------------------------
# FASTAPI APPLICATION
# ---------------------------------------------------------

app = FastAPI(
    title="MarketMind AI - Trading Intelligence Backend",
    version="1.0.0",
    lifespan=lifespan
)


# ---------------------------------------------------------
# EXISTING ROUTERS
# ---------------------------------------------------------

app.include_router(oi_signal_router)
app.include_router(confluence_router)
app.include_router(energy_router)
app.include_router(market_overview_router)
app.include_router(sector_oi_router)

app.include_router(weighted_setup_router)
app.include_router(live_crude_router)
app.include_router(trade_setup_router)
app.include_router(oi_reference_router)

app.include_router(kite_login_router)
app.include_router(auth_router)

# Excel recorder configuration API.
app.include_router(trade_excel_router)


# ---------------------------------------------------------
# DIRECT ALERTS
# ---------------------------------------------------------

install_direct_alerts(app)


# ---------------------------------------------------------
# SHARED STATE
# ---------------------------------------------------------

_lock = Lock()

_members = []
_members_at = 0.0

_snapshot = None
_snapshot_at = 0.0


# ---------------------------------------------------------
# NIFTY 50 CONSTITUENTS
# ---------------------------------------------------------

def constituents():

    global _members, _members_at

    if (
        _members
        and time.monotonic() - _members_at < 21600
    ):
        return _members

    path = BASE / "nifty50.csv"

    try:

        if path.exists():

            content = path.read_text(
                encoding="utf-8-sig"
            )

        else:

            response = requests.get(
                "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv",
                headers={
                    "User-Agent": "Mozilla/5.0"
                },
                timeout=12
            )

            response.raise_for_status()

            content = response.content.decode(
                "utf-8-sig"
            )

        members = [
            {
                "symbol": row["Symbol"].strip(),
                "sector": row.get("Industry", "").strip()
            }
            for row in csv.DictReader(
                io.StringIO(content)
            )
        ]

        if (
            len(members) != 50
            or len({
                member["symbol"]
                for member in members
            }) != 50
        ):

            raise ValueError(
                "Expected 50 unique symbols"
            )

        _members = members
        _members_at = time.monotonic()

        return _members

    except Exception:

        raise HTTPException(
            503,
            "Cannot load NIFTY 50 constituents. "
            "Download the official constituent CSV "
            "as backend/nifty50.csv."
        ) from None


configure_constituents(constituents)


# ---------------------------------------------------------
# ROOT
# ---------------------------------------------------------

@app.get("/")
def root():

    return {
        "app": "MarketMind AI API",
        "status": "online",
        "docs_url": "/docs"
    }


# ---------------------------------------------------------
# HEALTH
# ---------------------------------------------------------

@app.get("/api/health")
def health():

    return {
        "status": "healthy",
        "kite_status": kite_manager.get_status(),
        "kite_websocket": kite_stream.get_status()
    }


# ---------------------------------------------------------
# MARKET QUOTES
# ---------------------------------------------------------

@app.get("/api/market/quotes")
def live_quotes(
    symbols: Optional[str] = Query(None)
):

    try:

        return scanner_quotes()

    except HTTPException:

        raise

    except Exception:

        raise HTTPException(
            503,
            "Actual Kite stock quotes unavailable. "
            "Check token and connectivity; "
            "no sample rows were substituted."
        ) from None


# ---------------------------------------------------------
# MARKET SPOT STATE
# ---------------------------------------------------------

market_state = {
    "NIFTY_SPOT": 22859.14,
    "BANKNIFTY_SPOT": 49112.60
}


class SpotUpdate(BaseModel):

    symbol: str
    spot: float


@app.post("/api/market/spot")
def update_spot(payload: SpotUpdate):

    symbol = payload.symbol.upper()

    market_state[symbol] = payload.spot

    return {
        "message": (
            f"Updated {symbol} spot to {payload.spot}"
        ),
        "new_spot": payload.spot
    }


# ---------------------------------------------------------
# OPTIONS EXPIRIES
# ---------------------------------------------------------

@app.get("/api/options/expiries")
def expiries():

    return {
        "expiries": get_upcoming_expiries()
    }


# ---------------------------------------------------------
# LIVE OPTIONS CHAIN
# ---------------------------------------------------------

@app.get("/api/options/chain")
def option_chain(

    symbol: str = Query("NIFTY"),

    expiry: Optional[str] = Query(None),

    num_strikes: int = Query(
        25,
        ge=3,
        le=50
    ),

    spot: Optional[float] = Query(None)

):

    current_spot = (
        spot
        if spot is not None
        else market_state.get(
            symbol.upper(),
            22859.14
        )
    )

    return get_dynamic_option_chain(
        symbol=symbol,
        expiry=expiry,
        num_strikes=num_strikes,
        custom_spot=current_spot
    )


# ---------------------------------------------------------
# HISTORICAL OPTIONS CHAIN - AVAILABLE DATES
# ---------------------------------------------------------

@app.get("/api/options/history/dates")
def option_history_dates(

    symbol: str = Query("NIFTY")

):

    return get_option_history_dates(
        symbol=symbol
    )


# ---------------------------------------------------------
# HISTORICAL OPTIONS CHAIN - SELECTED DATE
# ---------------------------------------------------------

@app.get("/api/options/history")
def historical_option_chain(

    symbol: str = Query("NIFTY"),

    history_date: str = Query(...),

    expiry: Optional[str] = Query(None),

    num_strikes: int = Query(
        7,
        ge=3,
        le=50
    )

):

    return get_historical_option_chain(
        symbol=symbol,
        history_date=history_date,
        expiry=expiry,
        num_strikes=num_strikes
    )


# ---------------------------------------------------------
# CHART HISTORICAL CANDLES
# ---------------------------------------------------------

@app.get("/api/chart/candles")
def chart_candles(

    symbol: str = Query("NIFTY"),

    timeframe: str = Query("5m"),

    count: int = Query(
        60,
        ge=20,
        le=1000
    ),

    session: bool = Query(False)

):

    data = get_chart_data(
        symbol=symbol,
        timeframe=timeframe,
        count=count,
        session=session
    )

    token = data.get("instrument_token")

    if token:
        kite_stream.subscribe(token)

    return data


# ---------------------------------------------------------
# SELECTED OPTION CONTRACT CHART
# ---------------------------------------------------------

@app.get("/api/chart/option-candles")
def option_chart_candles(
    symbol: str = Query("NIFTY"),
    expiry: str = Query(...),
    strike: float = Query(..., gt=0),
    option_type: str = Query("CE"),
    timeframe: str = Query("15m"),
    count: int = Query(1000, ge=20, le=1000),
    session: bool = Query(True)
):

    return get_option_chart_data(
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        option_type=option_type,
        timeframe=timeframe,
        count=count,
        session=session
    )


# ---------------------------------------------------------
# CHART TICK
# ---------------------------------------------------------

@app.get("/api/chart/tick")
def chart_tick(

    symbol: str = Query("NIFTY"),

    timeframe: str = Query("5m")

):

    data = get_chart_data(
        symbol=symbol,
        timeframe=timeframe,
        count=2
    )

    token = data.get("instrument_token")

    if token:
        kite_stream.subscribe(token)

    return {
        "latest_tick": data["latest_tick"],
        "indicators": data["indicators"]
    }


# ---------------------------------------------------------
# CHART LIVE - KITE WEBSOCKET
# ---------------------------------------------------------

@app.get("/api/chart/live")
def chart_live(

    symbol: str = Query("NIFTY")

):

    if symbol not in (
        "NIFTY",
        "NIFTY_FUT"
    ):

        raise HTTPException(
            422,
            "Supported symbols: NIFTY, NIFTY_FUT"
        )

    data = get_chart_data(
        symbol=symbol,
        timeframe="1m",
        count=2
    )

    token = data.get("instrument_token")

    if not token:

        raise HTTPException(
            503,
            "Instrument token unavailable"
        )

    kite_stream.subscribe(token)

    tick = kite_stream.get_tick(token)

    return {
        **tick,
        "symbol": symbol,
        "instrument": data.get("instrument"),
        "quote_key": data.get("quote_key")
    }


# ---------------------------------------------------------
# GLOBAL CORS MIDDLEWARE
# ---------------------------------------------------------

allowed_origins = get_allowed_origins()

print(
    "[CORS] Allowed origins:",
    allowed_origins
)

# Wrap the complete FastAPI application.
# CORS headers will also be applied to error responses.
app = CORSMiddleware(
    app=app,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600
)


# ---------------------------------------------------------
# END
# ---------------------------------------------------------
