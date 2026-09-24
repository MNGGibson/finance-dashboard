-- Example category rules. Patterns are case-insensitive substrings of the bank description;
-- the highest priority match wins. Anything on a credit card that matches nothing is
-- spending:discretionary. Categories the dashboard understands:
--   income:*                 money in (income:paycheck, income:<side gig>)
--   bill:*                   fixed bills from cash (rent, car_loan, student_loan, family, annual_fee)
--   bill:debt_payment        payments to credit cards: kept apart so card spending is not counted twice
--   transfer:*               nets to zero (points redemptions and the like): ignored in totals
-- Load with: python scripts/rules.py load db/category_rules.example.sql
INSERT INTO category_rules (pattern, category, priority) SELECT '%your employer%', 'income:paycheck', 10 WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '%your employer%');
INSERT INTO category_rules (pattern, category, priority) SELECT '%your landlord%', 'bill:rent', 10 WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '%your landlord%');
INSERT INTO category_rules (pattern, category, priority) SELECT '%your loan servicer%', 'bill:student_loan', 10 WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '%your loan servicer%');
INSERT INTO category_rules (pattern, category, priority) SELECT '%amex epayment%', 'bill:debt_payment', 5 WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '%amex epayment%');
INSERT INTO category_rules (pattern, category, priority) SELECT '%pay with points credit%', 'transfer:points_redemption', 20 WHERE NOT EXISTS (SELECT 1 FROM category_rules WHERE pattern = '%pay with points credit%');
