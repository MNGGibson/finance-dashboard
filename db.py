"""Postgres access shared by the app, the sync script and the CLI tools.

Everything that talks to the database goes through here, so connection options and
the local time zone are set in one place.
"""
import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# Transactions are stored in UTC. The dashboard reasons in calendar days, so they are
# converted to this zone before the date is read off. Defaults to the machine's zone.
LOCAL_TZ = os.environ.get("LOCAL_TZ") or datetime.now().astimezone().tzinfo


def get_conn():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=os.environ.get("POSTGRES_PORT", "5432"),
        dbname=os.environ.get("POSTGRES_DB", "finance"),
        user=os.environ.get("POSTGRES_USER", "finance"),
        password=os.environ["POSTGRES_PASSWORD"],
        # A stalled Docker daemon should fail the caller quickly, not hang it forever.
        connect_timeout=10,
    )


def query(sql, params=None):
    """Run a SELECT and return a DataFrame. Uses a plain cursor: pandas.read_sql
    warns on every call when handed a psycopg2 connection."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [col.name for col in cur.description]
        rows = cur.fetchall()
    conn.close()
    df = pd.DataFrame(rows, columns=columns)
    # psycopg2 hands NUMERIC columns back as Decimal; the dashboard does float arithmetic.
    for column in df.columns:
        if df[column].map(lambda v: isinstance(v, Decimal)).any():
            df[column] = df[column].astype(float)
    return df


def to_local_naive(series):
    """UTC-aware timestamps -> naive timestamps in LOCAL_TZ, for calendar-day arithmetic."""
    return pd.to_datetime(series, utc=True).dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
