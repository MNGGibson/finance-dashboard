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


def setting(name, default=None):
    """A configuration value from the environment, or from Streamlit's secret store when
    the app runs on Streamlit Community Cloud (where secrets are not environment variables)."""
    value = os.environ.get(name)
    if value is not None:
        return value
    try:
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001  (no Streamlit, or no secrets file: fall through)
        pass
    return default


# Transactions are stored in UTC. The dashboard reasons in calendar days, so they are
# converted to this zone before the date is read off. Defaults to the machine's zone,
# which is UTC on cloud hosts, so set LOCAL_TZ there (for example America/New_York).
LOCAL_TZ = setting("LOCAL_TZ") or datetime.now().astimezone().tzinfo


def connection_kwargs():
    """Either DATABASE_URL (a hosted Postgres such as Neon, TLS required) or the discrete
    POSTGRES_* settings for the local Docker database."""
    url = setting("DATABASE_URL")
    if url:
        kwargs = {"dsn": url}
        if "sslmode=" not in url:
            kwargs["sslmode"] = "require"
    else:
        kwargs = {
            "host": setting("POSTGRES_HOST", "localhost"),
            "port": setting("POSTGRES_PORT", "5432"),
            "dbname": setting("POSTGRES_DB", "finance"),
            "user": setting("POSTGRES_USER", "finance"),
            "password": setting("POSTGRES_PASSWORD"),
        }
        if kwargs["password"] is None:
            raise KeyError("POSTGRES_PASSWORD (or DATABASE_URL) is not set")
    # A stalled database should fail the caller quickly, not hang it forever; a hosted one
    # that scales to zero needs a few seconds to wake, so it gets longer.
    kwargs["connect_timeout"] = 30 if url else 10
    return kwargs


def get_conn():
    return psycopg2.connect(**connection_kwargs())


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
