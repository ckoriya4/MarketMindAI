
from datetime import datetime, date, time as dt_time, timedelta
from backend.services import oi_signal as shared

IST = datetime.now().astimezone().tzinfo

kite = shared.kite_client()
today = date.today()

with shared.lock:
    instruments = shared.instruments(kite, today)

options = [
    row for row in instruments
    if row.get("name") == "NIFTY"
    and row.get("instrument_type") == "CE"
    and row.get("expiry")
    and shared.expiry_date(row["expiry"]) >= today
]

if not options:
    print("No currently listed NIFTY CE contracts found.")
    raise SystemExit

spot = kite.quote(["NSE:NIFTY 50"])["NSE:NIFTY 50"]["last_price"]

nearest_expiry = min(shared.expiry_date(r["expiry"]) for r in options)
expiry_options = [
    r for r in options
    if shared.expiry_date(r["expiry"]) == nearest_expiry
]

contract = min(
    expiry_options,
    key=lambda r: abs(float(r["strike"]) - spot)
)

print("Contract:", contract["tradingsymbol"])
print("Instrument token:", contract["instrument_token"])
print("Expiry:", nearest_expiry)

start = datetime(2026, 11, 17, 9, 15)
end = datetime(2026, 11, 23, 15, 30)

try:
    candles = kite.historical_data(
        contract["instrument_token"],
        start,
        end,
        "15minute",
        oi=True
    )

    print("Historical records:", len(candles))

    if candles:
        print("First record:", candles[0])
        print("Last record:", candles[-1])
        print("Available fields:", list(candles[0].keys()))
    else:
        print("Kite returned no historical records for this contract.")

except Exception as exc:
    print("Kite historical API error:", type(exc).__name__, str(exc))
