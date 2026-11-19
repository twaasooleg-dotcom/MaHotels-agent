param([ValidateSet('check','run','resume-batch','status','retry-held','test-topic')][string]$Command = 'status')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Open START.cmd once to create the MaHotels environment.' }
$sensitiveNames = @('WP_APP_PASSWORD','GROQ_API_KEY','GEMINI_API_KEY','CF_ACCOUNT_ID','CF_API_TOKEN','MAH_FREE_CONFIRMED','WP_USERNAME')
$result = 1
try {
    if ($Command -in @('run','resume-batch','check','test-topic')) {
        # Never import ArabiaTrend files or reuse its environment credentials.
        foreach ($name in $sensitiveNames) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
        $secretsDir = Join-Path $env:LOCALAPPDATA 'MaHotelsAgent'
        $confirmation = Get-Content -LiteralPath (Join-Path $secretsDir 'free-tier-confirmed.json') -Raw | ConvertFrom-Json
        if ($confirmation.free_only -ne $true) { throw 'Run START.cmd and confirm free-plan projects locally.' }
        if ($Command -in @('run','resume-batch','check')) {
            $wp = Import-Clixml -LiteralPath (Join-Path $secretsDir 'wordpress-credential.xml')
            if ($wp.UserName -cne 'ma_news_agent') { throw 'Expected WordPress username ma_news_agent.' }
            $env:WP_USERNAME = $wp.UserName
            $env:WP_APP_PASSWORD = $wp.GetNetworkCredential().Password
        }
        $keys = Import-Clixml -LiteralPath (Join-Path $secretsDir 'api-secrets.xml')
        foreach ($name in @('GROQ_API_KEY','GEMINI_API_KEY','CF_ACCOUNT_ID','CF_API_TOKEN')) {
            if (!$keys.ContainsKey($name)) { throw "Missing MaHotels credential: $name" }
            $value = [System.Net.NetworkCredential]::new('', $keys[$name]).Password
            [Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
        $env:MAH_FREE_CONFIRMED = '1'
    }
    $env:PYTHONUTF8 = '1'
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    & $python -B -X utf8 (Join-Path $PSScriptRoot 'agent.py') $Command
    $result = $LASTEXITCODE
} finally {
    foreach ($name in $sensitiveNames) { [Environment]::SetEnvironmentVariable($name, $null, 'Process') }
}
# Exactly one scheduled invocation daily. No automatic retry/resume tasks.
exit $result
