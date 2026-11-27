
"""Automatic daily Excel recorder for CALL BUY / PUT BUY setup signals."""

import json
import math
import sqlite3
import threading
import uuid

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field


# ============================================================
# CONFIGURATION
# ============================================================

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
_warning_lock = threading.Lock()

_last_warning = None


# ============================================================
# COMMON HELPERS
# ============================================================

def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def log_warning(message):
    global _last_warning

    message = str(message)

    with _warning_lock:
        if message == _last_warning:
            return

        _last_warning = message

    print("[TradeExcelRecorder] Recording warning:", message)


def clear_warning():
    global _last_warning

    with _warning_lock:
        _last_warning = None


# ============================================================
# SQLITE DATABASE
# ============================================================

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


# ============================================================
# SAVE COMPLETE CONFIG
# ============================================================

def save_config(expiry=None, risk_budget=None):

    if risk_budget is not None:
        if not number(risk_budget) or risk_budget <= 0:
            raise HTTPException(
                status_code=422,
                detail="Risk budget must be greater than zero."
            )

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

    result = {
        "saved": True,
        "expiry": expiry,
        "risk_budget": risk_budget,
    }

    print(
        "[TradeExcelRecorder] Config saved | "
        f"Expiry: {expiry} | "
        f"Risk Budget: {risk_budget}"
    )

    return result


# ============================================================
# UPDATE EXPIRY ONLY
# ============================================================

def save_expiry_only(expiry):

    if expiry is not None:
        expiry = str(expiry).strip() or None

    now = datetime.now(IST).isoformat()

    with _db_lock:
        with connect_db() as db:
            db.execute("""
                INSERT INTO recorder_config
                    (id, expiry, risk_budget, updated_at)
                VALUES (1, ?, NULL, ?)

                ON CONFLICT(id) DO UPDATE SET
                    expiry = excluded.expiry,
                    updated_at = excluded.updated_at
            """, (expiry, now))

            db.commit()

    print(
        "[TradeExcelRecorder] Expiry updated without "
        "changing Risk Budget:",
        expiry
    )


# ============================================================
# READ CONFIG
# ============================================================

def read_config():

    with _db_lock:
        with connect_db() as db:
            row = db.execute("""
                SELECT expiry, risk_budget
                FROM recorder_config
                WHERE id = 1
            """).fetchone()

    if not row:
        return {
            "expiry": None,
            "risk_budget": None,
        }

    return {
        "expiry": row["expiry"],
        "risk_budget": row["risk_budget"],
    }


# ============================================================
# SIGNAL STATE
# ============================================================

def read_state(key):

    with _db_lock:
        with connect_db() as db:
            row = db.execute("""
                SELECT state_json
                FROM recorder_state
                WHERE state_key = ?
            """, (key,)).fetchone()

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


# ============================================================
# EXCEL WORKBOOK - EXACTLY TWO SHEETS
# ============================================================

SIGNAL_HEADERS = [
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
]

LTP_HEADERS = [
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
]


def workbook_path(now):

    return EXCEL_DIR / (
        f"MarketMindAI_Signals_{now.strftime('%Y-%m-%d')}.xlsx"
    )


def style_header(ws):

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")


def get_workbook(now):

    path = workbook_path(now)

    if path.exists():
        wb = load_workbook(path)
    else:
        wb = Workbook()

    required_sheets = [
        "Signal Entries",
        "LTP Tracking",
    ]

    for sheet_name in list(wb.sheetnames):
        if sheet_name not in required_sheets:
            del wb[sheet_name]

    if "Signal Entries" not in wb.sheetnames:

        if len(wb.sheetnames) == 1 and wb.active.max_row == 1:
            wb.active.title = "Signal Entries"
        else:
            wb.create_sheet("Signal Entries")

    if "LTP Tracking" not in wb.sheetnames:
        wb.create_sheet("LTP Tracking")

    signal_ws = wb["Signal Entries"]
    ltp_ws = wb["LTP Tracking"]

    if signal_ws.max_row == 1 and signal_ws["A1"].value is None:
        signal_ws.append(SIGNAL_HEADERS)

    elif signal_ws["A1"].value != SIGNAL_HEADERS[0]:
        signal_ws.insert_rows(1)

        for index, header in enumerate(SIGNAL_HEADERS, start=1):
            signal_ws.cell(row=1, column=index, value=header)

    if ltp_ws.max_row == 1 and ltp_ws["A1"].value is None:
        ltp_ws.append(LTP_HEADERS)

    elif ltp_ws["A1"].value != LTP_HEADERS[0]:
        ltp_ws.insert_rows(1)

        for index, header in enumerate(LTP_HEADERS, start=1):
            ltp_ws.cell(row=1, column=index, value=header)

    style_header(signal_ws)
    style_header(ltp_ws)

    return wb, path


def create_daily_workbook():

    now = datetime.now(IST)

    with _excel_lock:
        wb, path = get_workbook(now)

        try:
            wb.save(path)
        finally:
            wb.close()

    print(f"[TradeExcelRecorder] Excel workbook ready: {path}")

    return path


def append_excel(signal, event=None):

    now = datetime.now(IST)

    with _excel_lock:
        wb, path = get_workbook(now)

        try:

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

        finally:
            wb.close()


def append_initial_ltp(signal):

    append_excel(
        signal,
        {
            "event": "INITIAL",
            "current_ltp": signal["initial_ltp"],
            "change_pct": 0.0,
        }
    )


# ============================================================
# SIGNAL PROCESSING
# ============================================================

def make_signal_id():
    return str(uuid.uuid4())


def reset_signal_state(state_key):

    state = {
        "active": False,
        "last_score": None,
        "unique_id": None,
        "initial_ltp": None,
        "expiry": None,
        "strike": None,
        "option_type": None,
        "trading_symbol": None,
        "seen_up": False,
        "seen_down": False,
    }

    save_state(state_key, state)


def process_card(action, card, config, expiry, quote_time):

    dashboard_score = card.get("score")
    base_score = card.get("base_score")

    risk_budget = config.get("risk_budget")

    # ========================================================
    # IMPORTANT CHANGE:
    # ALWAYS USE BASE SCORE FOR EXCEL SIGNAL SELECTION.
    #
    # Risk Budget and Dashboard Score do not affect
    # the Excel recorder's 60% entry condition.
    # ========================================================

    score = base_score

    print(
        f"[TradeExcelRecorder] Checking {action} | "
        f"Dashboard Score: {dashboard_score} | "
        f"Base Score: {base_score} | "
        f"Risk Budget: {risk_budget} | "
        f"Selected Score (BASE): {score}"
    )

    if not number(score):

        print(
            f"[TradeExcelRecorder] Skipped {action}: "
            f"Invalid Base Score: {base_score!r}"
        )

        return

    score = float(score)

    state_key = (
        datetime.now(IST).strftime("%Y-%m-%d")
        + ":"
        + action
    )

    state = read_state(state_key)

    # --------------------------------------------------------
    # BELOW 60%: RESET ACTIVE SIGNAL
    # --------------------------------------------------------

    if score < MIN_SCORE:

        print(
            f"[TradeExcelRecorder] {action} BASE score is "
            f"{score:.2f}%, below {MIN_SCORE}%."
        )

        if state.get("active"):

            print(
                f"[TradeExcelRecorder] Resetting active "
                f"{action} signal because Base Score is below 60%."
            )

            reset_signal_state(state_key)

        return

    # --------------------------------------------------------
    # GET ACTUAL EXECUTION LTP
    # --------------------------------------------------------

    execution = card.get("execution") or {}
    legs = execution.get("legs") or []

    if not legs:

        print(
            f"[TradeExcelRecorder] Skipped {action}: "
            "Execution legs are missing; score trigger will be "
            "checked again on the next fresh polling cycle."
        )

        return

    leg = legs[0]
    ltp = leg.get("ltp")

    if not number(ltp) or ltp <= 0:

        print(
            f"[TradeExcelRecorder] Skipped {action}: "
            f"Invalid execution LTP: {ltp}; score trigger will be "
            "checked again on the next fresh polling cycle."
        )

        return

    ltp = float(ltp)

    current_contract = {
        "expiry": expiry,
        "strike": leg.get("strike"),
        "option_type": leg.get("type"),
        "trading_symbol": leg.get("symbol"),
    }

    same_contract = (
        state.get("expiry") == current_contract["expiry"]
        and state.get("strike") == current_contract["strike"]
        and state.get("option_type") == current_contract["option_type"]
        and state.get("trading_symbol") == current_contract["trading_symbol"]
    )

    previous_score = state.get("last_score")
    active = state.get("active", False)

    # New entry conditions:
    # 1. No active signal.
    # 2. Base Score changes by >= 5 percentage points
    #    compared with the LAST RECORDED ENTRY score.
    # 3. Contract changes.
    #
    # The comparison is absolute, so increases and decreases
    # both trigger a new entry. Exactly 5.00 also triggers.

    score_difference = (
        abs(score - float(previous_score))
        if number(previous_score)
        else None
    )

    score_changed = (
        score_difference is not None
        and score_difference >= SCORE_STEP
    )

    new_entry = (
        not active
        or not number(previous_score)
        or score_changed
        or not same_contract
    )

    print(
        f"[TradeExcelRecorder] Entry decision | {action} | "
        f"Previous Recorded Base Score: {previous_score} | "
        f"Current Base Score: {score:.2f} | "
        f"Difference: "
        f"{score_difference:.2f}"
        f"{'%' if score_difference is not None else 'N/A'} | "
        f"Required: >= {SCORE_STEP:.2f} | "
        f"Active: {active} | Same Contract: {same_contract} | "
        f"New Entry: {new_entry}"
    )

    if not new_entry:
        print(
            f"[TradeExcelRecorder] No new {action} entry: "
            f"score difference is below {SCORE_STEP:.2f} "
            "and the contract has not changed."
        )

    # --------------------------------------------------------
    # CREATE NEW SIGNAL
    # --------------------------------------------------------

    if new_entry:

        unique_id = make_signal_id()

        signal = {
            "unique_id": unique_id,
            "action": action,
            "score": round(score, 2),
            "base_score": round(float(base_score), 2),
            "risk_budget": risk_budget,
            "expiry": expiry,
            "strike": leg.get("strike"),
            "option_type": leg.get("type"),
            "trading_symbol": leg.get("symbol"),
            "instrument_token": leg.get("instrument_token"),
            "initial_ltp": ltp,
            "oi": leg.get("oi"),
            "oi_change": leg.get("oi_change"),
            "oi_change_pct": leg.get("oi_change_pct"),
            "quote_time": quote_time,
        }

        # Sheet 1: Signal entry.
        append_excel(signal)

        # Sheet 2: Initial LTP baseline.
        append_initial_ltp(signal)

        # Queue user notifications only after both Excel writes succeed.
        # Delivery is asynchronous and idempotent by signal unique_id.
        try:
            from .notification_service import enqueue_signal_notification
            enqueue_signal_notification(signal)
        except Exception as exc:
            print(
                "[TradeExcelRecorder] Notification enqueue warning:",
                str(exc)
            )

        state = {
            "active": True,
            "last_score": round(score, 2),
            "unique_id": unique_id,
            "initial_ltp": ltp,
            "expiry": expiry,
            "strike": leg.get("strike"),
            "option_type": leg.get("type"),
            "trading_symbol": leg.get("symbol"),
            "seen_up": False,
            "seen_down": False,
        }

        save_state(state_key, state)

        print(
            f"[TradeExcelRecorder] New signal: "
            f"{action} | Base Score: {score:.2f}% | "
            f"ID: {unique_id} | LTP: {ltp}"
        )

        return

    # --------------------------------------------------------
    # MONITOR EXISTING SIGNAL
    # --------------------------------------------------------

    initial_ltp = state.get("initial_ltp")

    if not number(initial_ltp) or initial_ltp <= 0:

        print(
            f"[TradeExcelRecorder] Skipped LTP tracking for "
            f"{action}: Invalid initial LTP."
        )

        return

    change_pct = (
        (ltp - float(initial_ltp)) / float(initial_ltp)
    ) * 100

    signal = {
        "unique_id": state["unique_id"],
        "action": action,
        "expiry": expiry,
        "strike": leg.get("strike"),
        "option_type": leg.get("type"),
        "initial_ltp": float(initial_ltp),
    }

    # +20% EVENT

    if change_pct >= LTP_MOVE and not state.get("seen_up"):

        append_excel(
            signal,
            {
                "event": "+20%",
                "current_ltp": ltp,
                "change_pct": round(change_pct, 2),
            }
        )

        state["seen_up"] = True

        print(
            f"[TradeExcelRecorder] +20% reached: "
            f"{action} | ID: {state['unique_id']} | "
            f"Change: {change_pct:.2f}%"
        )

    # -20% EVENT

    elif change_pct <= -LTP_MOVE and not state.get("seen_down"):

        append_excel(
            signal,
            {
                "event": "-20%",
                "current_ltp": ltp,
                "change_pct": round(change_pct, 2),
            }
        )

        state["seen_down"] = True

        print(
            f"[TradeExcelRecorder] -20% reached: "
            f"{action} | ID: {state['unique_id']} | "
            f"Change: {change_pct:.2f}%"
        )

    save_state(state_key, state)


# ============================================================
# BACKGROUND RECORDER
# ============================================================

class TradeExcelRecorder:

    def __init__(self):

        self._stop = threading.Event()
        self._thread = None

    def start(self):

        initialize_db()

        try:
            create_daily_workbook()

        except Exception as exc:

            print(
                f"[TradeExcelRecorder] Excel creation failed: {exc}"
            )

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
            self._thread.join(timeout=30)

        if self._thread and self._thread.is_alive():

            print(
                "[TradeExcelRecorder] Stop requested; "
                "recording cycle is still finishing."
            )

        else:

            print("[TradeExcelRecorder] Stopped.")

    def _run(self):

        while not self._stop.is_set():

            try:

                self.record_once()
                clear_warning()

            except Exception as exc:

                log_warning(exc)

            self._stop.wait(POLL_SECONDS)

    # --------------------------------------------------------
    # EXPIRY VALIDATION
    # --------------------------------------------------------

    def get_valid_expiry(self, config):

        from .option_chain import get_upcoming_expiries

        valid_expiries = get_upcoming_expiries("NIFTY")

        if not valid_expiries:

            log_warning(
                "No valid NIFTY expiry returned by Kite."
            )

            return None

        requested_expiry = config.get("expiry")

        expiry_map = {
            str(item).strip().upper(): item
            for item in valid_expiries
        }

        selected_expiry = None

        if requested_expiry:

            selected_expiry = expiry_map.get(
                str(requested_expiry).strip().upper()
            )

        if selected_expiry is None:

            selected_expiry = valid_expiries[0]

            print(
                "[TradeExcelRecorder] Invalid/missing expiry:",
                repr(requested_expiry),
                "-> Using valid expiry:",
                selected_expiry,
            )

            save_expiry_only(selected_expiry)

            config["expiry"] = selected_expiry

        return selected_expiry

    # --------------------------------------------------------
    # ONE RECORDING CYCLE
    # --------------------------------------------------------

    def record_once(self):

        config = read_config()

        print(
            "[TradeExcelRecorder] Config loaded from SQLite | "
            f"Expiry: {config.get('expiry')} | "
            f"Risk Budget: {config.get('risk_budget')}"
        )

        from .trade_setups import setups

        selected_expiry = self.get_valid_expiry(config)

        if not selected_expiry:

            print(
                "[TradeExcelRecorder] Recording skipped: "
                "No valid expiry."
            )

            return

        # Keep existing dashboard setup request.
        # Excel selection independently uses Base Score.
        result = setups(
            expiry=selected_expiry,
            risk_budget=config.get("risk_budget"),
        )

        if not isinstance(result, dict):

            print(
                "[TradeExcelRecorder] Recording skipped: "
                "Trade setups returned a non-dictionary result."
            )

            return

        if result.get("status") != "fresh":

            print(
                "[TradeExcelRecorder] Recording skipped: "
                f"Setup status is {result.get('status')!r}, "
                "expected 'fresh'."
            )

            return

        quote_time = result.get("quote_time")

        if not number(quote_time):

            print(
                "[TradeExcelRecorder] Recording skipped: "
                f"Invalid quote_time: {quote_time!r}"
            )

            return

        actual_expiry = (
            result.get("expiry")
            or selected_expiry
        )

        cards = result.get("cards", [])

        if not isinstance(cards, list):

            print(
                "[TradeExcelRecorder] Recording skipped: "
                "Result cards are not a list."
            )

            return

        print(
            f"[TradeExcelRecorder] Fresh setup received | "
            f"Expiry: {actual_expiry} | "
            f"Cards: {len(cards)}"
        )

        for action in ("CALL BUY", "PUT BUY"):

            card = next(
                (
                    item
                    for item in cards
                    if isinstance(item, dict)
                    and item.get("action") == action
                ),
                None,
            )

            if card is None:

                print(
                    f"[TradeExcelRecorder] {action} card "
                    "not found in setup response."
                )

                continue

            process_card(
                action=action,
                card=card,
                config=config,
                expiry=actual_expiry,
                quote_time=quote_time,
            )


# ============================================================
# SINGLETON
# ============================================================

trade_excel_recorder = TradeExcelRecorder()


# ============================================================
# API CONFIGURATION
# ============================================================

class RecorderConfig(BaseModel):

    expiry: str | None = None

    risk_budget: float | None = Field(
        default=None,
        gt=0,
    )


@router.post("/api/signals/trade-setups/recorder-config")
def update_recorder_config(payload: RecorderConfig):

    result = save_config(
        expiry=payload.expiry,
        risk_budget=payload.risk_budget,
    )

    print(
        "[TradeExcelRecorder] Config updated | "
        f"Expiry: {result['expiry']} | "
        f"Risk Budget: {result['risk_budget']}"
    )

    return result


@router.get("/api/signals/trade-setups/recorder-config")
def get_recorder_config():

    return read_config()
