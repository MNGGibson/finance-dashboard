#!/usr/bin/env python3
"""Send a failure alert: an email (when SMTP is configured in .env) and a macOS notification.

    python scripts/notify.py "Daily sync failed" "SimpleFIN error: connection needs re-authorization"
    python scripts/notify.py --test          # send a test message to check the setup

Email needs these in .env (Gmail: create an App Password under Google Account > Security):
    NOTIFY_EMAIL=you@example.com          # where alerts go
    SMTP_USER=you@gmail.com               # the sending account
    SMTP_PASSWORD=xxxx xxxx xxxx xxxx     # its app password, never the real password
    SMTP_HOST=smtp.gmail.com              # optional, this is the default
    SMTP_PORT=587                         # optional, this is the default
Without them the script only shows the macOS notification and says so on stderr.
"""

import argparse
import os
import platform
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402, F401  (loads .env)


def macos_notification(title, body):
    if platform.system() != "Darwin":
        return
    safe = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    subprocess.run(
        [
            "osascript",
            "-e",
            f'display notification "{safe(body[:200])}" with title "Finance dashboard" subtitle "{safe(title)}"',
        ],
        check=False,
        capture_output=True,
    )


def send_email(title, body):
    """Returns True when sent, False when email is not configured. Raises on a send error."""
    to = os.environ.get("NOTIFY_EMAIL")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (to and user and password):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[Finance dashboard] {title}"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(
        f"{title}\n\n{body}\n\nMachine: {platform.node()}\nLogs: finance-dashboard/logs/sync.log and sync.err.log\n"
    )
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password.replace(" ", ""))
        smtp.send_message(msg)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("title", nargs="?", default="Test alert")
    parser.add_argument("body", nargs="?", default="If you can read this, failure emails are working.")
    parser.add_argument("--test", action="store_true", help="send a test message")
    args = parser.parse_args()

    macos_notification(args.title, args.body)
    try:
        if send_email(args.title, args.body):
            print(f"Emailed {os.environ['NOTIFY_EMAIL']}: {args.title}")
        else:
            print(
                "Email not configured (set NOTIFY_EMAIL, SMTP_USER, SMTP_PASSWORD in .env); "
                "showed a macOS notification only.",
                file=sys.stderr,
            )
            sys.exit(2 if args.test else 0)
    except (OSError, smtplib.SMTPException) as e:
        print(f"Email failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
