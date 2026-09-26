# Finance Dashboard

[![CI](https://github.com/MNGGibson/finance-dashboard/actions/workflows/ci.yml/badge.svg)](https://github.com/MNGGibson/finance-dashboard/actions/workflows/ci.yml)

Pulls balances & transactions from linked bank accounts via [SimpleFIN](https://www.simplefin.org/) into local Postgres, auto-categorizes them into income/bills/discretionary spending, and surfaces a live dashboard on top:

- **A Streamlit app** — a live dashboard with net worth, cross-filtering monthly KPIs, spending by category, spending trends, and promotional-APR deadlines flagged on the accounts that have them

It reads from a local Postgres database, kept up to date by a daily sync script.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, data model, and the reasoning behind the key decisions.

## 1. Start Postgres

```bash
cp .env.example .env
# edit .env and set a real POSTGRES_PASSWORD

docker compose up -d
```

Postgres is now running with the schema in `db/schema.sql` already applied.

## 2. Get a SimpleFIN access URL

1. Go to [bridge.simplefin.org](https://bridge.simplefin.org/), create an account, and link your bank(s).
2. Generate a **setup token** (a one-time-use base64 string) for a new app connection.
3. Exchange it for a persistent access URL:

```bash
python3.12 -m venv .venv   # any Python 3.10+; 3.9 is past end of life
source .venv/bin/activate
pip install -r requirements.txt

python scripts/setup.py "<PASTE_SETUP_TOKEN_HERE>"
```

This writes `SIMPLEFIN_ACCESS_URL` into `.env`. It's a credential — `.env` is already gitignored, keep it that way.

## 3. Run the first sync

```bash
source .venv/bin/activate  # if not already active
python scripts/sync.py               # default lookback window
python scripts/sync.py --days 90     # request more history (bank/bridge may cap it)
```

Pulls all accounts and transactions, upserts them into Postgres (`accounts`, `transactions`, `balance_snapshots`), and auto-tags each transaction using `category_rules` (see below).

## 4. Set up categorization rules

Transactions get tagged `income:*`, `bill:*`, or `spending:discretionary` via substring rules, so the dashboards can tell "money in" from "required bills" from "stuff I chose to buy." Start from the example file, then edit the patterns to match your bank's descriptions:

```bash
python scripts/rules.py load db/category_rules.example.sql   # seed
python scripts/rules.py list                                  # see what is loaded
python scripts/rules.py export > db/category_rules.local.sql  # keep your own copy (gitignored)
```

Or insert rows directly:

```sql
INSERT INTO category_rules (pattern, category, priority) VALUES
  ('%your employer name%', 'income:paycheck', 10),
  ('%your landlord/rent platform%', 'bill:rent', 10),
  ('%your loan servicer%', 'bill:student_loan', 10);
```

Any credit-card charge that doesn't match a rule falls back to `spending:discretionary` automatically — that's what powers the "Spending" and "daily spend average" metrics without needing a rule for every merchant. After changing rules, `python scripts/sync.py --recategorize` applies them to everything already stored.

## 5. Run the Streamlit app

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at http://localhost:8501. `app.py` handles page setup; the dashboard lives in `views/overview.py`, the accounting rules in `rules.py`, database access in `db.py`, and `ui.py` holds the shared design tokens, stat tiles, and chart styling. Dates are shown in the machine's time zone (override with `LOCAL_TZ` in `.env`). Theme colours are in `.streamlit/config.toml`.

- **Dashboard** — net worth as the lead number with an assets-versus-debt bar, then a row of tiles for the selected month: income, bills, card spending, and what is left for debt and savings (the first three add up to the fourth), plus what was paid to cards. Each compares with the same stretch of the previous month. The **Show** control cross-filters the category chart, a top-merchants chart, the account list, and transactions together. Trend charts cover spending pace, monthly cash flow, and spending per day.

The charts are interactive. Click a category bar and the merchant chart and transactions narrow to it; click a merchant bar and the transactions narrow again; click the bar once more, or empty space, to clear. Click a month in the cash flow or spending-per-day chart and the whole dashboard switches to that month. The spending pace chart has a crosshair that reads both months at the day under the pointer. Streamlit only reports clicks from single-layer Altair charts, so the clickable ones carry their amounts in the row labels rather than in a separate text layer.

Run the tests with `pip install -r requirements-dev.txt && pytest`. They cover the merchant parser and the accounting rules in `rules.py`.

Two rules keep the months honest. Card payments are shown apart from bills and outflows, because they settle card spending that is already counted. Rent posted in the last three days of a month counts toward the month it pays for. Merchant names are cleaned up from raw bank descriptions by `merchants.py`, a heuristic, so that grouping is approximate.

Manage categories and card APRs from the CLI:

```bash
python scripts/set_category.py --find "zelle"              # list matching transactions with ids
python scripts/set_category.py <transaction_id> income:paycheck   # tag one by hand; syncs leave it alone
python scripts/sync.py --recategorize                      # re-run the rules over everything not tagged by hand
```


```bash

python scripts/set_apr.py --list                        # see current APRs
python scripts/set_apr.py <account_id> 24.99             # set one
```

## 6. Run it as a service

Two launchd agents keep everything running without a terminal: one serves the dashboard on http://localhost:8511, the other runs the sync every six hours (1:17, 7:17, 13:17 and 19:17). SimpleFIN allows 24 pulls a day and refreshes each bank once a day at its own time, so four pulls catch every refresh within hours.

```bash
for name in dashboard sync; do
  sed "s#/path/to/finance-dashboard#$PWD#g" launchd/com.financedashboard.$name.plist > ~/Library/LaunchAgents/com.financedashboard.$name.plist
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.financedashboard.$name.plist
done
```

Both run through `scripts/ensure_docker.sh`, which starts Docker Desktop if it is not running, so a reboot does not leave them without a database. The sync wrapper (`scripts/run_sync.sh`) fetches 14 days each run, since card charges post days after they happen, and raises a macOS notification if a run fails. Once a day, on the first sync that finds no dump for the date, `scripts/backup_db.sh` dumps the database to `BACKUP_DIR` (default `~/Backups/finance-dashboard`; set it in `.env` to change), keeps the last 30 dumps, and mirrors the newest one to a `Backups/finance-dashboard` folder in iCloud Drive when iCloud Drive is set up (`ICLOUD_DIR` overrides the location). macOS restricts what background jobs may do inside iCloud Drive, so the mirror is best effort and a refusal is logged rather than treated as a failure.

When the sync or the backup fails you get a macOS notification, and an email if you set `NOTIFY_EMAIL`, `SMTP_USER` and `SMTP_PASSWORD` in `.env` (for Gmail, an App Password from Google Account → Security). Check the setup with `python scripts/notify.py --test`.

Those alerts can only fire if the sync actually runs. For the case where the Mac is off or asleep all day, set `HEALTHCHECK_URL` in `.env` to a [healthchecks.io](https://healthchecks.io) ping URL: every run checks in (start, success or failure), and if the daily check-in is missed the service emails you from outside the Mac. A period of one day with a grace of around twelve hours suits a laptop that syncs whenever it wakes. To also have the Mac wake itself for the morning run: `sudo pmset repeat wakeorpoweron MTWRFSU 07:15:00`. SimpleFIN only serves 90 days of history, so these dumps are the only copy of anything older. Restore with `gunzip -c finance-<date>.sql.gz | docker exec -i finance-postgres psql -U finance finance`. Logs land in `logs/`. To stop one: `launchctl bootout gui/$(id -u)/com.financedashboard.<name>`. After a code change, restart the dashboard with `launchctl kickstart -k gui/$(id -u)/com.financedashboard.dashboard` (it caches database reads for 5 minutes).

Cash-on-hand snapshots (used by the Overview page to show what cash looked like in *past* months, not just today) come from whichever daily sync lands closest to the 15th of each month — no separate job needed, this just falls out of running the sync daily.

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .   # lint and formatting, same as CI
pytest                                  # merchant parser, accounting rules, sync error handling
scripts/install-hooks.sh                # pre-commit hook: refuses commits containing words listed in .private-words
```

CI runs the same lint and tests on every push. Dependencies are pinned in `requirements.txt`; upgrade deliberately and re-run the tests. Schema changes for an existing database go in `db/migrations/NNN_name.sql` and are applied with `python scripts/migrate.py`; `db/schema.sql` stays the full schema for a fresh install.

## Schema

- **accounts** — one row per linked account: latest balance, `account_type` (checking/savings/credit_card/loan, set manually), `apr`/`promo_apr_expires`/`post_promo_apr` for tracking intro-rate deadlines (set manually via `scripts/set_apr.py`).
- **transactions** — one row per transaction, keyed by SimpleFIN's transaction id (upserted, so re-syncing is safe). `category` is populated by `category_rules` on every sync.
- **balance_snapshots** — one row per account *per sync run*, so balances/net worth are queryable over time.
- **category_rules** — description-substring → category mapping (`income:*`, `bill:*`), applied by `scripts/sync.py`; unmatched credit-card charges fall back to `spending:discretionary`.
