-- Where a transaction's category came from (rule, merchant, keyword, model, manual) and,
-- when the model corrected it, why. Lets later passes leave reviewed rows alone.
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS category_source TEXT;
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS category_note TEXT;
