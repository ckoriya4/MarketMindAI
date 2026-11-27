-- Run once against the PostgreSQL database configured by DATABASE_URL.
CREATE TABLE IF NOT EXISTS mm_users (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    email VARCHAR(254) NOT NULL UNIQUE,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mm_auth_otps (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES mm_users(id) ON DELETE CASCADE,
    purpose VARCHAR(30) NOT NULL,
    channel VARCHAR(10) NOT NULL CHECK (channel IN ('email','phone')),
    otp_hash TEXT NOT NULL,
    salt VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mm_auth_otps_user_created
    ON mm_auth_otps(user_id, purpose, created_at DESC);

CREATE TABLE IF NOT EXISTS mm_signal_outbox (
    signal_id VARCHAR(80) PRIMARY KEY,
    payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS mm_notification_deliveries (
    id BIGSERIAL PRIMARY KEY,
    signal_id VARCHAR(80) NOT NULL REFERENCES mm_signal_outbox(signal_id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES mm_users(id) ON DELETE CASCADE,
    channel VARCHAR(12) NOT NULL CHECK (channel IN ('email','sms','whatsapp')),
    destination VARCHAR(254) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(signal_id, user_id, channel)
);
CREATE INDEX IF NOT EXISTS idx_mm_delivery_pending
    ON mm_notification_deliveries(status, next_attempt_at);
