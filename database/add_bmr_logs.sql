CREATE TABLE IF NOT EXISTS bmr_logs (
    id BIGSERIAL PRIMARY KEY,
    challenger_id BIGINT NOT NULL REFERENCES challengers(id) ON DELETE CASCADE,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female')),
    birthday DATE NOT NULL,
    height_feet INTEGER NOT NULL CHECK (height_feet >= 0 AND height_feet <= 7),
    height_inches INTEGER NOT NULL CHECK (height_inches >= 0 AND height_inches <= 12),
    weight_lbs NUMERIC(6, 2) NOT NULL CHECK (weight_lbs > 0 AND weight_lbs <= 500),
    bmr NUMERIC(8, 2) NOT NULL,
    logged_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS bmr_logs_challenger_id_logged_at_idx
    ON bmr_logs (challenger_id, logged_at DESC);
