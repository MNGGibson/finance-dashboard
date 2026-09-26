"""Who may view the dashboard when it is hosted.

Streamlit Community Cloud signs viewers in before a private app loads and exposes the
viewer's email as st.user.email. With ALLOWED_VIEWERS set (comma-separated emails), the
app refuses anyone else even if it were made public by mistake. Unset, as on the local
Mac, everything is allowed.
"""

import db


def allowed_viewers(raw=None):
    raw = db.setting("ALLOWED_VIEWERS") if raw is None else raw
    return {email.strip().lower() for email in (raw or "").split(",") if email.strip()}


def viewer_email(user):
    """Email of the signed-in viewer, from a st.user-like mapping, or ''."""
    if user is None:
        return ""
    try:
        return (user.get("email") or "").strip().lower()
    except (AttributeError, TypeError, KeyError):
        return ""


def viewer_allowed(user, raw=None):
    allowed = allowed_viewers(raw)
    if not allowed:
        return True
    return viewer_email(user) in allowed
