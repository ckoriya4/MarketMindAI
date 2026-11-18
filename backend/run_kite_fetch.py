import os
import sys
import json
import argparse
from pathlib import Path

# Ensure the project root is in PYTHONPATH so relative imports work
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from services.kite_client import kite_manager
from services.option_chain import get_dynamic_option_chain


def ensure_token():
    """Make sure we have a valid Kite access token.
    If the stored token is invalid, guide the user through the login flow,
    generate a new session and write the new token back to the .env file.
    """
    status = kite_manager.get_status()
    if status["is_connected"]:
        # Already connected – nothing to do
        return

    print("[Kite] Not connected – starting authentication flow.")
    api_key = os.getenv("KITE_API_KEY")
    api_secret = os.getenv("KITE_API_SECRET")
    if not api_key or not api_secret:
        print("[Error] Missing KITE_API_KEY or KITE_API_SECRET in .env")
        sys.exit(1)

    # Initialise a temporary KiteConnect instance to obtain the login URL
    try:
        from kiteconnect import KiteConnect
    except ImportError:
        print("[Error] kiteconnect package not installed. Run 'pip install -r backend/requirements.txt'")
        sys.exit(1)

    kc = KiteConnect(api_key=api_key)
    login_url = kc.login_url()
    import webbrowser
    # Open the login URL automatically in the default browser
    print("Opening Kite login URL in your default browser…")
    webbrowser.open(login_url, new=2)
    # Prompt the user to paste the request token after they authenticate
    request_token = input("After logging in, you will be redirected to a URL containing \"request_token=...\". Please copy that token and paste here: ").strip()

    try:
        session = kc.generate_session(request_token, api_secret=api_secret)
        access_token = session.get("access_token")
        if not access_token:
            raise ValueError("No access_token returned")
    except Exception as e:
        print(f"[Kite] Failed to generate session: {e}")
        sys.exit(1)

    # Write the new token back to the .env file (same directory as this script)
    env_path = Path(__file__).resolve().parent / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    token_written = False
    for i, line in enumerate(lines):
        if line.startswith("KITE_ACCESS_TOKEN="):
            lines[i] = f"KITE_ACCESS_TOKEN={access_token}\n"
            token_written = True
            break
    if not token_written:
        lines.append(f"KITE_ACCESS_TOKEN={access_token}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    # Refresh the manager so the new token is picked up
    kite_manager._init_client()
    if kite_manager.is_connected:
        print("[Kite] Authentication successful – token stored in .env")
    else:
        print("[Kite] Authentication failed after writing token. Running in simulation mode.")


def fetch_option_chain(symbol: str, expiry: str | None, num_strikes: int):
    """Fetch the dynamic option chain using live spot (if possible)."""
    data = get_dynamic_option_chain(
        symbol=symbol,
        expiry=expiry,
        num_strikes=num_strikes,
        custom_spot=None,  # let the service decide – live spot if connected
    )
    return data


def main():
    parser = argparse.ArgumentParser(description="Fetch live option‑chain data from Zerodha Kite (or simulated if not connected).")
    parser.add_argument("--symbol", default="NIFTY", help="Underlying instrument (e.g., NIFTY, BANKNIFTY).")
    parser.add_argument("--expiry", default=None, help="Expiry date in format DD-MMM-YYYY (e.g., 29-Aug-2024).")
    parser.add_argument("--num", type=int, default=7, help="Number of strikes on each side of ATM.")
    args = parser.parse_args()

    ensure_token()
    chain = fetch_option_chain(args.symbol.upper(), args.expiry, args.num)
    print(json.dumps(chain, indent=2, default=str))


if __name__ == "__main__":
    main()

