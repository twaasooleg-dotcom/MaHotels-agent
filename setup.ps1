param([switch]$ReplaceWordPressPassword)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host 'MaHotels Agent: one daily batch of 3 Arabic articles; publication at 12:00, 14:00, 18:00 Africa/Cairo.'
Write-Host 'Separate site/account: https://mahotels.net / ma_news_agent / Blog category 7 at noon/18:00; categories 7 + 1710 at 14:00. No tag required.'
Write-Host 'Each daily batch contains only 3 articles/images. WordPress scheduling starts after they pass review.'
Write-Host 'Use separate Groq Free, Gemini Free-project, and Cloudflare Workers Free credentials with no paid billing enabled.'
Write-Host 'Local budgets cannot prove or disable provider billing. Never use billed projects for free-only operation.'
$answer = Read-Host 'Confirm the three projects/accounts have no paid billing enabled. Type FREE'
if ($answer -cne 'FREE') { throw 'Setup stopped before installing or changing scheduled tasks.' }
$secretsDir = Join-Path $env:LOCALAPPDATA 'MaHotelsAgent'
New-Item -ItemType Directory -Path $secretsDir -Force | Out-Null
$wpFile = Join-Path $secretsDir 'wordpress-credential.xml'
if ($ReplaceWordPressPassword -or !(Test-Path -LiteralPath $wpFile)) {
    Write-Host 'Use Users > ma_news_agent > Application Passwords in WordPress. Do not enter the normal dashboard login password.'
    $password = Read-Host 'NEW WordPress Application Password for ma_news_agent on mahotels.net' -AsSecureString
    if ($password.Length -eq 0) { throw 'Empty WordPress password.' }
    if (Test-Path -LiteralPath $wpFile) {
        $backupPath = $wpFile + '.backup-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
        Copy-Item -LiteralPath $wpFile -Destination $backupPath -ErrorAction Stop
        Write-Host 'Previous encrypted WordPress credential backed up locally. Provider keys are unchanged.'
    }
    [PSCredential]::new('ma_news_agent', $password) | Export-Clixml -LiteralPath $wpFile
}
$keysFile = Join-Path $secretsDir 'api-secrets.xml'
if (Test-Path -LiteralPath $keysFile) { $keys = Import-Clixml -LiteralPath $keysFile } else { $keys = @{} }
foreach ($entry in @(
    @('GROQ_API_KEY','Separate Groq Free API key'),
    @('GEMINI_API_KEY','Separate Gemini free-project API key'),
    @('CF_ACCOUNT_ID','Cloudflare Workers Free Account ID'),
    @('CF_API_TOKEN','Cloudflare Workers AI API token for this account')
)) {
    if (!$keys.ContainsKey($entry[0])) {
        $secret = Read-Host $entry[1] -AsSecureString
        if ($secret.Length -eq 0) { throw 'Empty value. Run START.cmd again to finish.' }
        $keys[$entry[0]] = $secret
        $keys | Export-Clixml -LiteralPath $keysFile
    }
}
@{free_only=$true; checked_at=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $secretsDir 'free-tier-confirmed.json') -Encoding UTF8
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required; environment creation failed.' }
}
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; task unchanged.' }
& $python -B -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; task unchanged.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'run.ps1') check
if ($LASTEXITCODE -eq 3) { throw 'MaHotels is already running; setup check was not performed and task is unchanged. Wait for completion; run.ps1 status can show progress meanwhile.' }
if ($LASTEXITCODE -ne 0) { throw 'Connection/identity/taxonomy/model discovery failed; task unchanged. See state\agent.log.' }
. (Join-Path $PSScriptRoot 'task-control.ps1')
$oldResume = Get-ScheduledTask -TaskName 'MaHotels-Agent-Resume' -ErrorAction SilentlyContinue
if ($oldResume) { Unregister-ScheduledTask -TaskName 'MaHotels-Agent-Resume' -Confirm:$false }
Register-MaDailyTask
Write-Host 'READY: one daily batch at 06:00 Windows local time (Cairo on this PC).'
Write-Host 'No automatic resume tasks. Unfinished work is saved for the next daily invocation.'
Write-Host 'Keep this Windows account logged in and this PC on during preparation. WordPress publishes scheduled posts server-side.'
Write-Host 'STATUS.cmd: offline progress. PAUSE.cmd: stop preparation. Memory.md: project context.'
