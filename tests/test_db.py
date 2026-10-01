import db


def test_database_url_wins_and_requires_tls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host.neon.tech/finance")
    kwargs = db.connection_kwargs()
    assert kwargs["dsn"].startswith("postgresql://")
    assert kwargs["sslmode"] == "require"
    assert kwargs["connect_timeout"] == 30  # a hosted database may need to wake up


def test_database_url_keeps_its_own_sslmode(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/finance?sslmode=verify-full")
    assert "sslmode" not in db.connection_kwargs()


def test_discrete_settings_for_local_docker(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    kwargs = db.connection_kwargs()
    assert kwargs["host"] == "127.0.0.1" and kwargs["dbname"] == "finance" and kwargs["password"] == "x"
    assert kwargs["connect_timeout"] == 10


def test_setting_prefers_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_TZ", "America/Chicago")
    assert db.setting("LOCAL_TZ") == "America/Chicago"
    monkeypatch.delenv("LOCAL_TZ")
    assert db.setting("LOCAL_TZ", "fallback") == "fallback"


def test_clock_conversion_flips_the_date_in_local_time_not_utc():
    # 00:33 UTC on Oct 1 is 8:33 PM on Sep 30 in New York: the page must still say September.
    instant = "2026-10-01 00:33:00"
    assert str(db.to_local(instant, "America/New_York")) == "2026-09-30 20:33:00"
    assert db.to_local(instant, "America/New_York").normalize() == db.pd.Timestamp("2026-09-30")
    assert db.to_local(instant, "UTC").normalize() == db.pd.Timestamp("2026-10-01")
    assert db.to_local(instant, "Asia/Tokyo").normalize() == db.pd.Timestamp("2026-10-01")


def test_local_dates_follow_daylight_saving():
    # Noon UTC is 7 AM in January (EST) but 8 AM in July (EDT): a fixed offset gets one of them wrong.
    assert str(db.to_local("2026-01-15 12:00:00", "America/New_York")) == "2026-01-15 07:00:00"
    assert str(db.to_local("2026-07-15 12:00:00", "America/New_York")) == "2026-07-15 08:00:00"


def test_to_local_naive_uses_the_configured_zone(monkeypatch):
    monkeypatch.setattr(db, "LOCAL_TZ", "America/New_York")
    series = db.pd.Series(db.pd.to_datetime(["2026-10-01 00:33:00", "2026-01-15 12:00:00"], utc=True))
    assert [str(v) for v in db.to_local_naive(series)] == ["2026-09-30 20:33:00", "2026-01-15 07:00:00"]


def test_local_today_is_a_naive_date_in_the_zone():
    today = db.local_today("America/New_York")
    assert today.tzinfo is None and today == today.normalize()
