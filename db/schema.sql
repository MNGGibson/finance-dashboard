CREATE TABLE IF NOT EXISTS accounts (
    id            TEXT PRIMARY KEY,
    org_name      TEXT NOT NULL,
    name          TEXT NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    last_balance  NUMERIC(14, 2),
    balance_date  TIMESTAMPTZ,
    -- checking | savings | credit_card | loan; not provided by SimpleFIN, set manually
    account_type  TEXT,
    -- annual percentage rate for credit_card/loan accounts; not provided by SimpleFIN, set manually
    apr           NUMERIC(5, 2),
    -- if apr is a promo/balance-transfer rate, when it reverts to post_promo_apr
    promo_apr_expires  DATE,
    post_promo_apr     NUMERIC(5, 2),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transactions (
    id          TEXT PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    posted      TIMESTAMPTZ NOT NULL,
    amount      NUMERIC(14, 2) NOT NULL,
    description TEXT,
    pending     BOOLEAN NOT NULL DEFAULT false,
    -- e.g. income:paycheck, income:uber, bill:rent, bill:debt_payment; set by category_rules
    category    TEXT,
    -- true when set by hand (scripts/set_category.py); the sync then leaves category alone
    category_manual BOOLEAN NOT NULL DEFAULT false,
    raw         JSONB,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transactions_account_posted
    ON transactions (account_id, posted DESC);

-- One row per account per sync run, so balances over time (net worth trend) are queryable.
CREATE TABLE IF NOT EXISTS balance_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    account_id  TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    balance     NUMERIC(14, 2) NOT NULL,
    as_of       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_balance_snapshots_account_as_of
    ON balance_snapshots (account_id, as_of DESC);

-- Description substring -> category, applied by scripts/sync.py on every upsert.
-- Higher priority wins when multiple patterns match the same description.
CREATE TABLE IF NOT EXISTS category_rules (
    id        SERIAL PRIMARY KEY,
    pattern   TEXT NOT NULL,
    category  TEXT NOT NULL,
    priority  INT NOT NULL DEFAULT 0
);

-- Records which db/migrations/*.sql have run (scripts/migrate.py). Fresh databases get
-- the full schema above; migrations are for databases that already hold data.
CREATE TABLE IF NOT EXISTS schema_migrations (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
