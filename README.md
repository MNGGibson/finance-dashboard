# Finance Dashboard

Pulls balances & transactions from linked bank accounts via [SimpleFIN](https://www.simplefin.org/) into local Postgres, auto-categorizes them into income/bills/discretionary spending, and surfaces two views on top:

- **A Streamlit app** — a live dashboard with net worth, cross-filtering monthly KPIs, spending by category, spending trends, and promotional-APR deadlines flagged on the accounts that have them
- **Metabase** — plain BI-style dashboards and trend charts on the same data

Both read from the same Postgres database, kept up to date by a daily sync script.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the system design, data model, and the reasoning behind the key decisions.

## 1. Start Postgres + Metabase

```bash
cp .env.example .env
# edit .env and set a real POSTGRES_PASSWORD

docker compose up -d
```

Postgres is now running with the schema in `db/schema.sql` already applied. Metabase is at http://localhost:3000 — open it and click through the first-run setup wizard (create an admin account, skip adding a database for now).

## 2. Get a SimpleFIN access URL

1. Go to [bridge.simplefin.org](https://bridge.simplefin.org/), create an account, and link your bank(s).
2. Generate a **setup token** (a one-time-use base64 string) for a new app connection.
3. Exchange it for a persistent access URL:

```bash
python3 -m venv .venv
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

Transactions get tagged `income:*`, `bill:*`, or `spending:discretionary` via simple substring rules, so the dashboards can tell "money in" from "required bills" from "stuff I chose to buy." Seed your own rules directly in Postgres:

```sql
INSERT INTO category_rules (pattern, category, priority) VALUES
  ('%your employer name%', 'income:paycheck', 10),
  ('%your landlord/rent platform%', 'bill:rent', 10),
  ('%your loan servicer%', 'bill:student_loan', 10);
```

Any credit-card charge that doesn't match a rule falls back to `spending:discretionary` automatically — that's what powers the "Spending" and "daily spend average" metrics without needing a rule for every merchant.

## 5. Run the Streamlit app

```bash
source .venv/bin/activate
streamlit run app.py
```

Opens at http://localhost:8501. `app.py` handles page setup; the dashboard lives in `views/overview.py`, and `ui.py` holds the shared design tokens, stat tiles, and chart styling. Theme colours are in `.streamlit/config.toml`.

- **Dashboard** — net worth as the lead number with an assets-versus-debt bar, then a row of tiles for the selected month: income, bills, card spending, and what is left for debt and savings (the first three add up to the fourth), plus what was paid to cards. Each compares with the same stretch of the previous month. The **Show** control cross-filters the category chart, a top-merchants chart, the account list, and transactions together. Trend charts cover spending pace, monthly cash flow, and spending per day.

The charts are interactive. Click a category bar and the merchant chart and transactions narrow to it; click a merchant bar and the transactions narrow again; click the bar once more, or empty space, to clear. Click a month in the cash flow or spending-per-day chart and the whole dashboard switches to that month. The spending pace chart has a crosshair that reads both months at the day under the pointer. Streamlit only reports clicks from single-layer Altair charts, so the clickable ones carry their amounts in the row labels rather than in a separate text layer.

Two rules keep the months honest. Card payments are shown apart from bills and outflows, because they settle card spending that is already counted. Rent posted in the last three days of a month counts toward the month it pays for. Merchant names are cleaned up from raw bank descriptions by `merchants.py`, a heuristic, so that grouping is approximate.

Manage savings goals and card APRs from the CLI (Metabase has no easy write-back form for this):

```bash
python scripts/add_goal.py --list-accounts             # find an account id to link a goal to
python scripts/add_goal.py "Emergency fund" 5000 --account <id>
python scripts/add_goal.py --list                       # see progress (goals are CLI-only, not shown in the app)

python scripts/set_apr.py --list                        # see current APRs
python scripts/set_apr.py <account_id> 24.99             # set one
```

## 6. Automate daily syncs

```bash
cp launchd/com.financedashboard.sync.plist ~/Library/LaunchAgents/
# edit the copied file first: replace every /path/to/finance-dashboard with this project's real absolute path
launchctl load ~/Library/LaunchAgents/com.financedashboard.sync.plist
```

Runs daily at 7am. Logs land in `logs/sync.log` / `logs/sync.err.log`. To stop it: `launchctl unload ~/Library/LaunchAgents/com.financedashboard.sync.plist`.

Cash-on-hand snapshots (used by the Overview page to show what cash looked like in *past* months, not just today) come from whichever daily sync lands closest to the 15th of each month — no separate job needed, this just falls out of running the sync daily.

## 7. Connect Metabase to the data (optional, alongside Streamlit)

In Metabase (http://localhost:3000) → Admin settings → Databases → Add database → Postgres. Metabase and Postgres share the same Docker Compose network, so use `host: postgres` (the Compose service name), port `5432`, and the db/user/password from `.env`.

## Schema

- **accounts** — one row per linked account: latest balance, `account_type` (checking/savings/credit_card/loan, set manually), `apr`/`promo_apr_expires`/`post_promo_apr` for tracking intro-rate deadlines (set manually via `scripts/set_apr.py`).
- **transactions** — one row per transaction, keyed by SimpleFIN's transaction id (upserted, so re-syncing is safe). `category` is populated by `category_rules` on every sync.
- **balance_snapshots** — one row per account *per sync run*, so balances/net worth are queryable over time.
- **category_rules** — description-substring → category mapping (`income:*`, `bill:*`), applied by `scripts/sync.py`; unmatched credit-card charges fall back to `spending:discretionary`.
- **goals** — savings goals, each optionally linked to an account so progress is `current balance - starting balance`.
