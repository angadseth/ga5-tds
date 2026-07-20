# Render's free plan spins a service down after ~15 minutes idle, and the
# cold start takes long enough that the GA5 grader records REQUEST_TIMEOUT
# and counts the probe as failed. A cheap periodic hit keeps it awake.
try {
    $r = Invoke-WebRequest -Uri 'https://ga5-tds.onrender.com/health' -TimeoutSec 90 -UseBasicParsing
    "$(Get-Date -Format s)  $($r.StatusCode)" | Out-File -Append -Encoding utf8 "$PSScriptRoot\keepwarm.log"
} catch {
    "$(Get-Date -Format s)  ERR $($_.Exception.Message)" | Out-File -Append -Encoding utf8 "$PSScriptRoot\keepwarm.log"
}
