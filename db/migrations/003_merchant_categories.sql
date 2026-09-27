-- One row per merchant: which spending group it belongs to and where that came from.
-- source: manual (scripts/classify.py --set), seed, keyword, model (Gemini). Manual wins.
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant    TEXT PRIMARY KEY,           -- normalised name, see classify.merchant_key
    category    TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
