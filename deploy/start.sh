#!/bin/sh
set -e
cd /app/backend
# Free tier has no persistent disk: rebuild the demo database on every start (no AI calls, no API keys needed).
python seed.py --reset --synth ../tools/synth/output_demo
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}" --proxy-headers --forwarded-allow-ips="*"
