# Architecture

How this system is put together, and why it's built this way.

## Overview

One Postgres database is the single source of truth. A daily script pulls from SimpleFIN and categorizes every transaction on the way in. A Streamlit dashboard reads from that database: net worth, cross-filtering monthly KPIs, spending by category and merchant, and trends.

```mermaid
flowchart TD
    SF[SimpleFIN Bridge]
    SF -->|REST API| SYNC[scripts/sync.py]
    SYNC -->|categorize + upsert| PG[(Postgres)]

    SETUP[scripts/setup.py] -.one-time token exchange.-> SF
    LAUNCHD[launchd, every 6h] -.triggers.-> SYNC

    PG --> ST[Streamlit dashboard]

    CLI[scripts/set_category.py<br/>scripts/set_apr.py] -->|categories, APRs| PG
```

## Components

**Ingestion — `scripts/sync.py`**
Pulls accounts, balances, and transactions from the SimpleFIN API, then upserts them into Postgres. Idempotent by SimpleFIN's transaction id, so re-running it is always safe. Also writes a `balance_snapshots` row per account on every run, which is what makes historical balance trends possible later.

**Categorization engine — `category_rules` + `scripts/sync.py`**
Every transaction description is matched against substring rules in `category_rules` (`income:paycheck`, `bill:rent`, etc.), highest-priority match wins. Anything on a credit card that doesn't match any rule falls back to `spending:discretionary` automatically — that one fallback rule is what makes "spending" and "daily spend average" work without hand-tagging every merchant. Rules live in the database, not code, so they're editable without a deploy. A category set by hand (`scripts/set_category.py`) is flagged `category_manual` and the sync never overwrites it; `sync.py --recategorize` re-runs the rules over everything else, which matters because the daily sync only re-fetches a two-week window. The sync exits non-zero when SimpleFIN reports an error or returns no accounts, so a dead bank link fails loudly instead of quietly going stale.

**Storage — Postgres**
Runs in Docker, data lives in a named volume (never in the repo). Postgres rather than SQLite so any BI tool can be pointed at the same data later without a driver workaround.

**Presentation — Streamlit app**
Off-the-shelf BI tools can show and filter *stored* data, but can't cross-filter a whole page from one control so that every chart, list and table reconciles to the number you picked, or compare a partial month against the same stretch of the previous one. The dashboard exists for that. An earlier debt-payoff forecasting page was removed as not useful in practice; it is preserved on the `forecasting-archive` branch.

**Backups — `scripts/backup_db.sh`**
Runs once a day, on the first sync that finds no dump for the date: a compressed `pg_dump` into a local folder, thirty kept, plus the category rules as SQL, with the newest mirrored to iCloud Drive by plain shell redirection (the one write macOS lets a background job make there). SimpleFIN only serves 90 days of history, so the database is the only copy of anything older.

**Automation — launchd**
Two launchd agents: one keeps the dashboard running on localhost:8511, one runs the sync every six hours (SimpleFIN allows 24 pulls a day). Both go through `scripts/ensure_docker.sh`, which starts Docker Desktop if it is not running, so a reboot does not leave either without a database. The sync wrapper raises a macOS notification when a run fails.

## Data model

```mermaid
erDiagram
    accounts ||--o{ transactions : has
    accounts ||--o{ balance_snapshots : has
    category_rules ||..o{ transactions : "tags via pattern match"

    accounts {
        text id PK
        text org_name
        text name
        text account_type "checking/savings/credit_card/loan"
        numeric last_balance
        numeric apr
        date promo_apr_expires
        numeric post_promo_apr
    }
    transactions {
        text id PK
        text account_id FK
        timestamptz posted
        numeric amount
        text description
        text category "income:*/bill:*/spending:discretionary"
        jsonb raw
    }
    balance_snapshots {
        bigint id PK
        text account_id FK
        numeric balance
        timestamptz as_of "one row per account per sync run"
    }
    category_rules {
        int id PK
        text pattern "ILIKE substring"
        text category
        int priority
    }
```

## Key design decisions

**Rule-based categorization, not ML.** Transaction volume for one person is small (hundreds, not millions), the patterns are stable (an employer name doesn't change often), and rule-based means every categorization decision is inspectable and correctable in one SQL statement — no training data, no black box, no drift to monitor.

**Cash on hand is a monthly snapshot, not always today's live balance.** The Overview page lets you pick any past month. If "cash on hand" always showed today's number regardless of which month was selected, every past month would lie. Instead it picks the daily sync closest to the 15th of whichever month is selected, and shows "n/a" honestly for months before tracking started rather than fabricating a number.

**One filter state drives every visual (the `Show` control in `views/overview.py`).** Click "Bills" and the category chart, the account list, and the transaction list all filter from the *same* computed subset — not five independent filters that can drift out of sync. Totals are printed under each visual specifically so they can be eyeballed against each other and against the KPI itself.

**Spending, Bills, and Income are mutually exclusive by design.** A credit card payment is a required outflow, not a discretionary purchase — conflating the two would make "Spending" mean nothing. `bill:*` (rent, loans, card payments, fees) and `spending:discretionary` (everything else charged) are deliberately separate categories so each KPI answers one specific question.

## Known limitations

- SimpleFIN caps transaction history at 90 days regardless of what's requested — there's no way to backfill years of history through the API; it only accumulates going forward.
- APRs and account types aren't provided by SimpleFIN and must be set manually (`scripts/set_apr.py`, direct SQL) since the data doesn't exist anywhere to sync it from.
- Single-user by design — no auth, no multi-tenancy. This is a personal tool, not a SaaS product.
- Category rules are hand-curated. A rule engine that guesses categories automatically would be a natural next step, but was deliberately skipped in favor of predictability.
