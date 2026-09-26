import db


def test_database_url_wins_and_requires_tls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host.neon.tech/finance")
    kwargs = db.connection_kwargs()
    assert kwargs["dsn"].startswith("postgresql://")
    assert kwargs["sslmode"] == "require"
    assert kwargs["connect_timeout"] == 10


def test_database_url_keeps_its_own_sslmode(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/finance?sslmode=verify-full")
    assert "sslmode" not in db.connection_kwargs()


def test_discrete_settings_for_local_docker(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    kwargs = db.connection_kwargs()
    assert kwargs["host"] == "127.0.0.1" and kwargs["dbname"] == "finance" and kwargs["password"] == "x"


def test_setting_prefers_environment(monkeypatch):
    monkeypatch.setenv("LOCAL_TZ", "America/Chicago")
    assert db.setting("LOCAL_TZ") == "America/Chicago"
    monkeypatch.delenv("LOCAL_TZ")
    assert db.setting("LOCAL_TZ", "fallback") == "fallback"
