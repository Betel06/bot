@echo off
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "try { Invoke-WebRequest -Uri 'https://bot-spot.onrender.com/health' -UseBasicParsing -TimeoutSec 90 | Out-Null } catch {}"
