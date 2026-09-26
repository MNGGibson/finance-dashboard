-- A read-only user for the dashboard, so a flaw in the web app cannot change history.
-- Run once against the hosted database, replacing the password, then use this user in the
-- dashboard's DATABASE_URL. The sync keeps using the owner user.
CREATE ROLE finance_ro WITH LOGIN PASSWORD 'replace-me';
GRANT CONNECT ON DATABASE finance TO finance_ro;
GRANT USAGE ON SCHEMA public TO finance_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO finance_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO finance_ro;
