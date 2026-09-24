#!/usr/bin/env python3
"""One-time exchange of a SimpleFIN setup token for a persistent access URL."""

import base64
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/setup.py <SIMPLEFIN_SETUP_TOKEN>")
        sys.exit(1)

    claim_url = base64.b64decode(sys.argv[1]).decode("utf-8")

    resp = requests.post(claim_url, timeout=30)
    resp.raise_for_status()
    access_url = resp.text.strip()

    env_path = ROOT / ".env"
    lines = []
    if env_path.exists():
        lines = [line for line in env_path.read_text().splitlines() if not line.startswith("SIMPLEFIN_ACCESS_URL=")]
    lines.append(f"SIMPLEFIN_ACCESS_URL={access_url}")
    env_path.write_text("\n".join(lines) + "\n")

    print(f"Saved SimpleFIN access URL to {env_path}")


if __name__ == "__main__":
    main()
