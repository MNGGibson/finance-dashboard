"""Postgres access shared by the app, the sync script and the CLI tools.

Everything that talks to the database goes through here, so connection options and
the local time zone are set in one place.
"""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

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


def _system_zone():
    """The machine's named time zone (so daylight saving is applied correctly), read from the
    /etc/localtime link on macOS and Linux. A fixed UTC offset is the last resort: it would be
    wrong for half the year and for any date on the other side of a clock change."""
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return ZoneInfo(target.split("zoneinfo/", 1)[1])
    except Exception:  # noqa: BLE001
        pass
    return datetime.now().astimezone().tzinfo


# Transactions are stored in UTC, and the dashboard reasons in calendar days: both "which day did
# this happen" and "what day is it now" are answered in this zone. A cloud host's clock is UTC, so
# set LOCAL_TZ there (for example America/New_York), or the page rolls to tomorrow at 8 PM Eastern.
LOCAL_TZ = setting("LOCAL_TZ") or _system_zone()


def to_local(instant, zone=None):
    """A UTC instant (naive means UTC) as a naive timestamp in `zone` (default LOCAL_TZ)."""
    stamp = pd.Timestamp(instant)
    stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
    return stamp.tz_convert(zone or LOCAL_TZ).tz_localize(None)


def local_now(zone=None):
    """The current local wall-clock time, naive. Use this, never pd.Timestamp.now() or date.today(),
    which read the server's clock and so give UTC dates on a cloud host."""
    return to_local(pd.Timestamp.now(tz="UTC"), zone)


def local_today(zone=None):
    return local_now(zone).normalize()


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
