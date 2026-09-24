-- Categories set by hand are kept through syncs (scripts/set_category.py).
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS category_manual BOOLEAN NOT NULL DEFAULT false;
