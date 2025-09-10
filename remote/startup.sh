#!/usr/bin/env bash

set -euo pipefail

sleep 10

echo "starting beest"

echo "pinging router"

while true; do ping -c1 192.168.8.1 && break; done

cd /home/pi/

ADDR=lt6.local python server.py
