# Watchdog do OmniRoute - mantem o gateway de IA vivo 24/7
$ErrorActionPreference = 'SilentlyContinue'
$log = "C:\Users\danie\Documents\BOT\omniroute_watchdog.log"
$vbs = 'C:\Users\danie\Documents\BOT\omniroute_hidden.vbs'

function Log($m) {
    Add-Content -Path $log -Value "$(Get-Date -Format 'dd/MM HH:mm:ss') $m" -ErrorAction SilentlyContinue
}

Log "watchdog iniciado (PID $PID)"

while ($true) {
    $listening = netstat -ano | Select-String ":20128\s+.+LISTENING"
    $procAlive = Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
        Where-Object { $_.CommandLine -like "*omniroute*" }

    if (-not $listening -and -not $procAlive) {
        $sh = New-Object -ComObject WScript.Shell
        $sh.Run('cmd /c "set OMNIROUTE_NO_OPEN=1 && omniroute"', 0, $false)
        Log "servidor morto -> disparei inicio oculto"
    }
    Start-Sleep -Seconds 30
}
