param([ValidateSet('pause','resume')][string]$Command)
$ErrorActionPreference = 'Stop'
$marker = Join-Path $PSScriptRoot 'PAUSE'
if ($Command -eq 'pause') {
    Set-Content -LiteralPath $marker -Value 'Paused locally' -Encoding UTF8
    foreach ($taskName in @('MaHotels-Agent','MaHotels-Agent-Resume')) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task) { $task | Disable-ScheduledTask | Out-Null }
    }
    Write-Host 'Paused at the next checkpoint. Existing WordPress future posts remain scheduled.'
} else {
    if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker }
    Enable-ScheduledTask -TaskName 'MaHotels-Agent' | Out-Null
    Write-Host 'MaHotels task enabled for its next daily window. No immediate extra run was started.'
}
