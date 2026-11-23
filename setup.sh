#!/bin/bash
# Holiday Finder — fresh instance setup
# Run: bash setup.sh
# Then access via SSH tunnel: ssh -p <PORT> -L 5001:localhost:5001 -N root@<HOST>

set -e
echo "=== Installing dependencies ==="
pip install -q flask playwright playwright-stealth aiohttp

echo "=== Installing Playwright Chromium ==="
playwright install chromium
playwright install-deps chromium

echo "=== Starting Holiday Finder GUI ==="
cp holiday_gui.py /root/holiday_gui.py 2>/dev/null || true
cd /root
nohup python holiday_gui.py > /root/holiday.log 2>&1 &
sleep 3
echo "=== Done! Server running on port 5001 ==="
echo "Access via: ssh -p <PORT> -L 5001:localhost:5001 -N root@<HOST>"
tail -5 /root/holiday.log
