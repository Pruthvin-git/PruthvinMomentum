# Task Scheduler — Nasdaq monthly momentum mail (weekdays 09:30 IST).
param([string]$EmailTo = "pruthvin98@gmail.com")

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_nasdaq_mail.ps1"
if (-not (Test-Path $Runner)) { Write-Error "Missing $Runner" }

$Name = "Nasdaq_Monthly"
$existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed existing task $Name"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -EmailTo `"$EmailTo`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ScriptDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "09:30"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "Nasdaq-100 6m ROC dual-mom Top-5 monthly. Strategy ndx|roc126|top5|M|dual. First US trading day of month." | Out-Null
Write-Host "Registered $Name Mon-Fri 09:30 IST (email only on first US trading day of month)"
Write-Host ""
Write-Host "Dry run (no email):"
Write-Host "  powershell -File `"$Runner`" -NoEmail -Force"
Write-Host "Send now:"
Write-Host "  powershell -File `"$Runner`" -Force"
