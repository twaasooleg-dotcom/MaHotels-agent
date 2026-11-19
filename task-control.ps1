function Get-MaTaskAction {
    New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PSScriptRoot\run.ps1`" run" -WorkingDirectory $PSScriptRoot
}

function Get-MaTaskPrincipal {
    New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
}

function Get-MaTaskSettings {
    $runtimeConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes ($runtimeConfig.max_run_minutes + 15)) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
}

function Register-MaDailyTask {
    $runtimeConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $firstRun = (Get-Date).Date.AddHours([int]$runtimeConfig.run_hour)
    if ($firstRun -le (Get-Date)) { $firstRun = $firstRun.AddDays(1) }
    $dailyTrigger = New-ScheduledTaskTrigger -Daily -DaysInterval 1 -At $firstRun
    Register-ScheduledTask -TaskName 'MaHotels-Agent' -Action (Get-MaTaskAction) -Trigger $dailyTrigger -Principal (Get-MaTaskPrincipal) -Settings (Get-MaTaskSettings) -Description 'One daily batch of three articles. Blog: 12/18; news + blog: 14 Africa/Cairo.' -Force | Out-Null
}
