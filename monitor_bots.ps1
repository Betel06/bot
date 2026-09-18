# Monitor simples dos 3 bots no Render (ping health, sem output)
$ErrorActionPreference = 'SilentlyContinue'
$urls = @(
    'https://bot-spot.onrender.com/health',
    'https://bot-futuro-acdj.onrender.com/health',
    'https://bot-b3.onrender.com/health'
)
foreach ($u in $urls) {
    Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 90 | Out-Null
}
