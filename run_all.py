# ------------------------------------------------------------
# run_all.py
# One‑click script that:
#   • ensures a .env file exists (copies from .env.example if needed),
#   • loads Kite API credentials,
#   • logs in to Kite (opens browser, asks for request token),
#   • writes the fresh access token back into backend/.env,
#   • fetches live NIFTY‑50 option‑chain data (51 strikes = 25 on each side of ATM),
#   • saves the JSON payload to latest_nifty_chain.json,
#   • prints a short human‑readable summary (ATM, R1, S1, DTE, AB‑Score).
# ------------------------------------------------------------

import os
import sys
import json
import webbrowser
from pathlib import Path

# ------------------------------------------------------------------
# Helper: make sure a .env file exists (copy from .env.example if missing)
# ------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
ENV_PATH = BACKEND_ROOT / ".env"
ENV_EXAMPLE = BACKEND_ROOT / ".env.example"

if not ENV_PATH.exists():
    if ENV_EXAMPLE.exists():
        ENV_PATH.write_bytes(ENV_EXAMPLE.read_bytes())
        print(f"[Setup] Created .env from .env.example at {ENV_PATH}")
    else:
        print("[Error] Neither .env nor .env.example exist. Abort.")
        sys.exit(1)

# ------------------------------------------------------------------
# Load environment variables (requires python‑dotenv)
# ------------------------------------------------------------------
try:
    from dotenv import load_dotenv
except ImportError:
    print("[Error] python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

load_dotenv(ENV_PATH)  # load variables from backend/.env

# ------------------------------------------------------------------
# Verify API key / secret are present
# ------------------------------------------------------------------
API_KEY = os.getenv("KITE_API_KEY", "").strip()
API_SECRET = os.getenv("KITE_API_SECRET", "").strip()

if not API_KEY or not API_SECRET:
    print("[Error] KITE_API_KEY or KITE_API_SECRET missing in .env.")
    print("Edit", ENV_PATH, "and paste the values you obtained from https://developers.kite.trade")
    sys.exit(1)

# ------------------------------------------------------------------
# Initialise / validate Kite client
# ------------------------------------------------------------------
def _init_kite_client():
    """Return dict with keys: kite (client or None), connected (bool), profile (dict or None)."""
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("[Error] kiteconnect package not installed. Run: pip install kiteconnect")
        sys.exit(1)

    access_token = os.getenv("KITE_ACCESS_TOKEN", "").strip()
    if API_KEY and access_token:
        try:
            kc = KiteConnect(api_key=API_KEY)
            kc.set_access_token(access_token)
            profile = kc.profile()
            if profile and "user_id" in profile:
                return {"kite": kc, "connected": True, "profile": profile}
        except Exception as e:
            print(f"[Kite] Existing token invalid ({e}) – will re‑authenticate.")
    return {"kite": None, "connected": False, "profile": None}

kite_state = _init_kite_client()

# ------------------------------------------------------------------
# If not connected, run interactive login flow
# ------------------------------------------------------------------
if not kite_state["connected"]:
    from kiteconnect import KiteConnect
    kc = KiteConnect(api_key=API_KEY)
    login_url = kc.login_url()
    print("\n[Kite] No valid session – starting authentication flow.")
    print("Opening the Kite login page in your default browser…")
    webbrowser.open(login_url, new=2)
    request_token = input(
        "\nAfter logging in, you will be redirected to a URL containing \"request_token=...\". "
        "Please copy that token and paste it here: "
    ).strip()
    try:
        session = kc.generate_session(request_token, api_secret=API_SECRET)
        new_token = session.get("access_token")
        if not new_token:
            raise ValueError("No access_token returned")
    except Exception as e:
        print(f"[Kite] Failed to generate session: {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Write the new access token back into backend/.env
    # ------------------------------------------------------------------
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    token_written = False
    for i, line in enumerate(lines):
        if line.startswith("KITE_ACCESS_TOKEN="):
            lines[i] = f"KITE_ACCESS_TOKEN={new_token}"
            token_written = True
            break
    if not token_written:
        lines.append(f"KITE_ACCESS_TOKEN={new_token}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[Kite] New access token stored in .env")

    # Refresh the client with the new token
    kite_state = _init_kite_client()
    if not kite_state["connected"]:
        print("[Kite] Unexpected: unable to connect even after writing token.")
        sys.exit(1)

# ------------------------------------------------------------------
# Fetch live option‑chain (NIFTY‑50) using the existing service function
# ------------------------------------------------------------------
# Ensure the backend package is importable
# Add the backend folder to PYTHONPATH so "services" can be imported
sys.path.append(str(BACKEND_ROOT))

from services.option_chain import get_dynamic_option_chain

symbol = "NIFTY"
num_strikes = 50  # 50 on each side → 101 strikes total (may be heavy)
print("\n[Fetch] Getting live option chain for NIFTY …")
chain_data = get_dynamic_option_chain(
    symbol=symbol,
    expiry=None,          # nearest expiry
    num_strikes=num_strikes,
    custom_spot=None     # let the service use the live spot price if connected
)

# ------------------------------------------------------------------
# Write JSON to file
# ------------------------------------------------------------------
OUTPUT_JSON = PROJECT_ROOT / "latest_nifty_chain.json"
OUTPUT_JSON.write_text(json.dumps(chain_data, indent=2, default=str), encoding="utf-8")
print(f"[Save] JSON written to {OUTPUT_JSON}")

# ------------------------------------------------------------------
# Human‑readable summary
# ------------------------------------------------------------------
atm = chain_data.get("atm_strike")
r1 = chain_data.get("r1")
s1 = chain_data.get("s1")
dte = chain_data.get("dte")
ab = chain_data.get("ab_score", {})

print("\n=== Summary ===")
print(f"Symbol          : {symbol}")
print(f"Expiry (nearest): {chain_data.get('expiry')}")
print(f"ATM strike      : {atm}")
print(f"R1 (Resistance) : {r1}")
print(f"S1 (Support)    : {s1}")
print(f"DTE (days)      : {dte}")
print(f"AB‑Score        : {ab.get('score')} → {ab.get('trend')}")
print("================\n")

sys.exit(0)

