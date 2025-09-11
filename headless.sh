#!/usr/bin/env bash
set -euo pipefail
sleep 2
echo "starting beest headless"
cd /home/pi/strandbeest
. .venv/bin/activate
CRONCH=0 python run.py
