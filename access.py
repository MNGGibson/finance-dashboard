"""Who may view the dashboard when it is hosted.

With ALLOWED_VIEWERS set (comma-separated emails), the app checks the signed-in viewer's
email (st.user.email) and refuses anyone else. It fails closed: if no email is visible,
nobody gets in. Unset, as on the local Mac, everything is allowed.

st.user.email is only populated when the app itself runs a sign-in, that is Streamlit's
[auth] configuration with an identity provider such as Google. On Streamlit Community
Cloud without [auth], the viewer's email is not exposed to the app (since Streamlit
1.42), so leave ALLOWED_VIEWERS unset there and rely on the private-app viewer list.
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
