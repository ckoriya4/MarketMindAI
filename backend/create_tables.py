
from services.database import get_db_connection


CREATE_TABLES = [

    # 1. Stock quotes
    """
    CREATE TABLE IF NOT EXISTS market_quotes (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        ltp DOUBLE PRECISION,
        change_percent DOUBLE PRECISION,
        volume BIGINT,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # 2. Option chain history
    """
    CREATE TABLE IF NOT EXISTS option_chain_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        expiry DATE,
        strike DOUBLE PRECISION NOT NULL,
        option_type TEXT NOT NULL,
        ltp DOUBLE PRECISION,
        oi BIGINT,
        oi_change BIGINT,
        volume BIGINT,
        iv DOUBLE PRECISION,
        delta DOUBLE PRECISION,
        gamma DOUBLE PRECISION,
        theta DOUBLE PRECISION,
        vega DOUBLE PRECISION,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # 3. Total Call OI / Put OI / PCR
    """
    CREATE TABLE IF NOT EXISTS oi_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        expiry DATE,
        call_oi BIGINT,
        put_oi BIGINT,
        pcr DOUBLE PRECISION,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # 4. Historical candles
    """
    CREATE TABLE IF NOT EXISTS candles_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        interval TEXT NOT NULL,
        candle_time TIMESTAMPTZ NOT NULL,
        open DOUBLE PRECISION,
        high DOUBLE PRECISION,
        low DOUBLE PRECISION,
        close DOUBLE PRECISION,
        volume BIGINT,
        UNIQUE(symbol, interval, candle_time)
    )
    """,

    # 5. Stock scanner snapshots
    """
    CREATE TABLE IF NOT EXISTS scanner_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        scanner_type TEXT NOT NULL,
        ltp DOUBLE PRECISION,
        change_percent DOUBLE PRECISION,
        volume BIGINT,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # 6. Crude oil history
    """
    CREATE TABLE IF NOT EXISTS crude_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        ltp DOUBLE PRECISION,
        change_percent DOUBLE PRECISION,
        volume BIGINT,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # 7. Trading signals
    """
    CREATE TABLE IF NOT EXISTS signals_history (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        signal_type TEXT,
        direction TEXT,
        strength DOUBLE PRECISION,
        details JSONB,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,

    # Indexes for faster historical queries
    """
    CREATE INDEX IF NOT EXISTS idx_market_quotes_symbol_time
    ON market_quotes(symbol, recorded_at DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_option_chain_symbol_time
    ON option_chain_history(symbol, recorded_at DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_oi_history_symbol_time
    ON oi_history(symbol, recorded_at DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_candles_symbol_time
    ON candles_history(symbol, interval, candle_time DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_scanner_history_time
    ON scanner_history(recorded_at DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_crude_history_time
    ON crude_history(recorded_at DESC)
    """,

    """
    CREATE INDEX IF NOT EXISTS idx_signals_history_time
    ON signals_history(recorded_at DESC)
    """
]


def create_tables():
    with get_db_connection() as conn:

        for query in CREATE_TABLES:
            conn.execute(query)

    print("PostgreSQL history tables created successfully!")
    print("News storage is excluded.")
    print("Total history tables: 7")


if __name__ == "__main__":
    create_tables()
