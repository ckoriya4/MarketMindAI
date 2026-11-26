
"""Automatic daily Excel recorder for CALL BUY / PUT BUY setup signals."""

import json
import math
import sqlite3
import threading
import time
import uuid

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field


IST = ZoneInfo("Asia/Kolkata")

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data"
EXCEL_DIR = BASE / "excel_reports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
EXCEL_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "trade_excel_recorder.sqlite3"

POLL_SECONDS = 10
MIN_SCORE = 60.0
SCORE_STEP = 5.0
LTP_MOVE = 20.0

router = APIRouter()

_db_lock = threading.RLock()
_excel_lock = threading.RLock()


def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def connect_db():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_db():
    with _db_lock:
        with connect_db() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS recorder_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    expiry TEXT,
                    risk_budget REAL,
                    updated_at TEXT
                )
            """)

            db.execute("""
                CREATE TABLE IF NOT EXISTS recorder_state (
                    state_key TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            db.commit()


def save_config(expiry=None, risk_budget=None):
    if risk_budget is not None:
        if not number(risk_budget) or risk_budget <= 0:
            raise HTTPException(422, "Risk budget must be greater than zero.")

    if expiry is not None:
        expiry = str(expiry).strip() or None

    now = datetime.now(IST).isoformat()

    with _db_lock:
        with connect_db() as db:
            db.execute("""
                INSERT INTO recorder_config
                    (id, expiry, risk_budget, updated_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    expiry = excluded.expiry,
                    risk_budget = excluded.risk_budget,
                    updated_at = excluded.updated_at
            """, (expiry, risk_budget, now))

            db.commit()

    return {
        "saved": True,
        "expiry": expiry,
        "risk_budget": risk_budget,
    }


def read_config():
    with _db_lock:
        with connect_db() as db:
            row = db.execute(
                "SELECT expiry, risk_budget FROM recorder_config WHERE id = 1"
            ).fetchone()

    if not row:
        return {"expiry": None, "risk_budget": None}

    return {
        "expiry": row["expiry"],
        "risk_budget": row["risk_budget"],
    }


def read_state(key):
    with _db_lock:
        with connect_db() as db:
            row = db.execute(
                "SELECT state_json FROM recorder_state WHERE state_key = ?",
                (key,),
            ).fetchone()

    if not row:
        return {}

    try:
        return json.loads(row["state_json"])
    except Exception:
        return {}


def save_state(key, state):
    with _db_lock:
        with connect_db() as db:
            db.execute("""
                INSERT INTO recorder_state
                    (state_key, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
            """, (
                key,
                json.dumps(state, ensure_ascii=False),
                datetime.now(IST).isoformat(),
            ))
            db.commit()


def workbook_path(now):
    return EXCEL_DIR / (
        f"MarketMindAI_Signals_{now.strftime('%Y-%m-%d')}.xlsx"
    )


def get_workbook(now):
    path = workbook_path(now)

    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()

        first = wb.active
        first.title = "Signal Entries"

        first.append([
            "Date",
            "Time (IST)",
            "Unique ID",
            "Action",
            "Score %",
            "Base Score %",
            "Risk Budget",
            "Expiry",
            "Strike",
            "Option Type",
            "Trading Symbol",
            "Instrument Token",
            "Initial LTP",
            "OI",
            "OI Change",
            "OI Change %",
            "Quote Time",
        ])

        second = wb.create_sheet("LTP Tracking")

        second.append([
            "Date",
            "Time (IST)",
            "Unique ID",
            "Action",
            "Expiry",
            "Strike",
            "Option Type",
            "Event",
            "Initial LTP",
            "Current LTP",
            "Change %",
        ])

        for sheet in wb.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions

            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill(
                    "solid",
                    fgColor="1F4E78",
                )

    return wb, path


def append_excel(signal, event=None):
    now = datetime.now(IST)

    with _excel_lock:
        wb, path = get_workbook(now)

        if event is None:
            ws = wb["Signal Entries"]

            ws.append([
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                signal["unique_id"],
                signal["action"],
                signal["score"],
                signal.get("base_score"),
                signal.get("risk_budget"),
                signal.get("expiry"),
                signal.get("strike"),
                signal.get("option_type"),
                signal.get("trading_symbol"),
                signal.get("instrument_token"),
                signal.get("initial_ltp"),
                signal.get("oi"),
                signal.get("oi_change"),
                signal.get("oi_change_pct"),
                signal.get("quote_time"),
            ])

        else:
            ws = wb["LTP Tracking"]

            ws.append([
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                signal["unique_id"],
                signal["action"],
                signal.get("expiry"),
                signal.get("strike"),
                signal.get("option_type"),
                event["event"],
                signal["initial_ltp"],
                event["current_ltp"],
                event["change_pct"],
            ])

        wb.save(path)


def make_signal_id():
    return str(uuid.uuid4())


def process_card(action, card, config, expiry, quote_time):
    score = card.get("score")
    base_score = card.get("base_score")

    # With a budget use the dashboard-adjusted score.
    # Without a budget use the unadjusted base score.
    if config.get("risk_budget") is None:
        score = base_score

    if not number(score):
        return

    state_key = (
        datetime.now(IST).strftime("%Y-%m-%d")
        + ":"
        + action
    )

    state = read_state(state_key)

    if score < MIN_SCORE:
        state.update({
            "active": False,
            "last_score": None,
            "unique_id": None,
            "initial_ltp": None,
            "seen_up": False,
            "seen_down": False,
        })
        save_state(state_key, state)
        return

    execution = card.get("execution") or {}
    legs = execution.get("legs") or []

    if not legs:
        return

    leg = legs[0]
    ltp = leg.get("ltp")

    # No fabricated LTP values.
    if not number(ltp) or ltp <= 0:
        return

    previous_score = state.get("last_score")
    active = state.get("active", False)

    new_entry = (
        not active
        or not number(previous_score)
        or abs(score - previous_score) >= SCORE_STEP
    )

    if new_entry:
        unique_id = make_signal_id()

        signal = {
            "unique_id": unique_id,
            "action": action,
            "score": round(float(score), 2),
            "base_score": base_score,
            "risk_budget": config.get("risk_budget"),
            "expiry": expiry,
            "strike": leg.get("strike"),
            "option_type": leg.get("type"),
            "trading_symbol": leg.get("symbol"),
            "instrument_token": leg.get("instrument_token"),
            "initial_ltp": float(ltp),
            "oi": leg.get("oi"),
            "oi_change": leg.get("oi_change"),
            "oi_change_pct": leg.get("oi_change_pct"),
            "quote_time": quote_time,
        }

        append_excel(signal)

        state = {
            "active": True,
            "last_score": round(float(score), 2),
            "unique_id": unique_id,
            "initial_ltp": float(ltp),
            "expiry": expiry,
            "strike": leg.get("strike"),
            "option_type": leg.get("type"),
            "trading_symbol": leg.get("symbol"),
            "seen_up": False,
            "seen_down": False,
        }

        save_state(state_key, state)
        return

    # Same signal ID: monitor its original contract only.
    same_contract = (
        state.get("expiry") == expiry
        and state.get("strike") == leg.get("strike")
        and state.get("option_type") == leg.get("type")
        and state.get("trading_symbol") == leg.get("symbol")
    )

    if not same_contract:
        return

    initial_ltp = state.get("initial_ltp")

    if not number(initial_ltp) or initial_ltp <= 0:
        return

    change_pct = (
        (float(ltp) - initial_ltp) / initial_ltp
    ) * 100

    signal = {
        "unique_id": state["unique_id"],
        "action": action,
        "expiry": expiry,
        "strike": leg.get("strike"),
        "option_type": leg.get("type"),
        "initial_ltp": initial_ltp,
    }

    if change_pct >= LTP_MOVE and not state.get("seen_up"):
        append_excel(
            signal,
            {
                "event": "+20%",
                "current_ltp": float(ltp),
                "change_pct": round(change_pct, 2),
            },
        )
        state["seen_up"] = True

    elif change_pct <= -LTP_MOVE and not state.get("seen_down"):
        append_excel(
            signal,
            {
                "event": "-20%",
                "current_ltp": float(ltp),
                "change_pct": round(change_pct, 2),
            },
        )
        state["seen_down"] = True

    save_state(state_key, state)


class TradeExcelRecorder:
    def __init__(self):
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        initialize_db()

        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()

        self._thread = threading.Thread(
            target=self._run,
            name="TradeExcelRecorder",
            daemon=True,
        )

        self._thread.start()

        print("[TradeExcelRecorder] Started.")

    def stop(self):
        self._stop.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=15)

        print("[TradeExcelRecorder] Stopped.")

    def _run(self):
        while not self._stop.is_set():
            try:
                self.record_once()
            except Exception as exc:
                print(
                    "[TradeExcelRecorder] Recording warning:",
                    str(exc),
                )

            self._stop.wait(POLL_SECONDS)

    def record_once(self):
        config = read_config()

        # Lazy import avoids circular imports at module startup.
        from .trade_setups import setups

        result = setups(
            expiry=config.get("expiry"),
            risk_budget=config.get("risk_budget"),
        )

        if not isinstance(result, dict):
            return

        if result.get("status") != "fresh":
            return

        quote_time = result.get("quote_time")
        if not number(quote_time):
            return

        expiry = result.get("expiry") or config.get("expiry")

        for action in ("CALL BUY", "PUT BUY"):
            card = next(
                (
                    item
                    for item in result.get("cards", [])
                    if item.get("action") == action
                ),
                None,
            )

            if card is None:
                continue

            process_card(
                action,
                card,
                config,
                expiry,
                quote_time,
            )


trade_excel_recorder = TradeExcelRecorder()


class RecorderConfig(BaseModel):
    expiry: str | None = None
    risk_budget: float | None = Field(default=None, gt=0)


@router.post("/api/signals/trade-setups/recorder-config")
def update_recorder_config(payload: RecorderConfig):
    return save_config(
        expiry=payload.expiry,
        risk_budget=payload.risk_budget,
    )


@router.get("/api/signals/trade-setups/recorder-config")
def get_recorder_config():
    return read_config()
