# Monitoramento Completo e Seguro
$bots = @(
    "https://bot-spot.onrender.com/health",
    "https://bot-futuro-acdj.onrender.com/health",
    "https://bot-b3.onrender.com/"
)

# 1. Manter bots Render vivos
foreach ($url in $bots) {
    try { Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 30 | Out-Null } catch {}
}

# 2. Monitorar Huntera (bot.js e Chrome)
$hunteraProc = Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } # Simplificado
if (-not $hunteraProc) {
    Write-Host "Huntera offline, reiniciando..."
    # Lógica de reinicio segura
    Start-Process "node" -ArgumentList "C:\Users\danie\Documents\huntera-bot\bot.js" -WorkingDirectory "C:\Users\danie\Documents\huntera-bot"
}
