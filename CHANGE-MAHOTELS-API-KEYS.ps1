$ErrorActionPreference = 'Stop'
$secretDirectory = Join-Path $env:LOCALAPPDATA 'MaHotelsAgent'
$secretFile = Join-Path $secretDirectory 'api-secrets.xml'
if (!(Test-Path -LiteralPath $secretDirectory)) {
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
}
if (Test-Path -LiteralPath $secretFile) {
    $keys = Import-Clixml -LiteralPath $secretFile
    if ($keys -isnot [System.Collections.IDictionary]) { throw 'Unexpected credential format. Existing file was not changed.' }
} else { $keys = @{} }

Write-Host 'MaHotels API key editor. Enter values locally; input is hidden.'
Write-Host 'Press Enter to keep an existing value. Use keys belonging to your confirmed free-plan projects.'
Write-Host 'Groq: text writing/fallback review. Gemini: text review, fallback writing and image inspection.'
Write-Host 'Cloudflare: square image generation. WordPress credentials and schedule are preserved.'
$changed = $false
foreach ($entry in @(
    @('GROQ_API_KEY','Groq API key'),
    @('GEMINI_API_KEY','Gemini API key'),
    @('CF_ACCOUNT_ID','Cloudflare Account ID'),
    @('CF_API_TOKEN','Cloudflare Workers AI API token')
)) {
    $newValue = Read-Host ($entry[1] + ' (Enter keeps current value)') -AsSecureString
    if ($newValue.Length -gt 0) {
        $keys[$entry[0]] = $newValue
        $changed = $true
    }
    if (!$keys.Contains($entry[0])) { throw ('Missing required value: ' + $entry[0] + '. Existing credentials were not changed.') }
}
if (!$changed) { Write-Host 'No values changed.'; exit 0 }

$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
$temporary = $secretFile + '.tmp-' + $stamp
$keys | Export-Clixml -LiteralPath $temporary
if (Test-Path -LiteralPath $secretFile) {
    Copy-Item -LiteralPath $secretFile -Destination ($secretFile + '.backup-' + $stamp) -ErrorAction Stop
}
Move-Item -LiteralPath $temporary -Destination $secretFile -Force
Write-Host 'Updated API credentials saved with Windows encryption; previous encrypted credentials backed up when present.'
Write-Host 'The next agent invocation will load the updated keys. No network requests were made by this editor.'
