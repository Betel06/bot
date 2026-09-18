@echo off
rem Keep-alive do OmniRoute (gateway IA local) - porta 20128
powershell -NoProfile -Command "$l = netstat -ano | Select-String ':20128\s+.+LISTENING'; $p = Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | Where-Object { $_.CommandLine -like '*omniroute*' }; if (-not $l -and -not $p) { Start-Process cmd -ArgumentList '/c','omniroute' -WindowStyle Minimized }"