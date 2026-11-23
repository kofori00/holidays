#!/bin/bash
# This file is run on instance start. Output in /var/log/onstart.log

pip install -q flask playwright playwright-stealth aiohttp
playwright install chromium
playwright install-deps chromium

cp /root/holiday_gui.py /root/holiday_gui.py 2>/dev/null || true
cd /root
nohup python holiday_gui.py > /root/holiday.log 2>&1 &
echo "Holiday Finder started on port 5001"
