#!/bin/bash
# launchd entry point for the dashboard: wait for Docker, then run Streamlit in place.
set -u
cd "$(dirname "$0")/.." || exit 1
scripts/ensure_docker.sh || exit 1
exec .venv/bin/streamlit run app.py --server.port 8511 --server.address localhost \
    --server.headless true --browser.gatherUsageStats false
