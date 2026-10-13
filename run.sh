#!/usr/bin/env sh
# Launch the Process Engineering Toolbox (local only)
cd "$(dirname "$0")"
if [ -x .venv/Scripts/streamlit ]; then exec .venv/Scripts/streamlit run launcher/app.py; fi
exec .venv/bin/streamlit run launcher/app.py
