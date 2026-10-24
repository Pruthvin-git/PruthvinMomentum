# Task Scheduler — Nifty 500 Top-10 monthly momentum mail (1st of month 09:30 IST).
param([string]$EmailTo = "pruthvin98@gmail.com")

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_nifty500_top10_monthly_mail.ps1"
if (-not (Test-Path $Runner)) { Write-Error "Missing $Runner" }

$Name = "Mom500_Nifty500_Top10_Monthly"
$existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Write-Host "Removed existing task $Name"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -EmailTo `"$EmailTo`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ScriptDir
# Day 1 each month; script only sends on first *trading* day (skips otherwise).
# Weekdays 09:30 — Python sends only on the first trading session of each month.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At "09:30"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "Nifty 500 63d ROC dual-mom Top-10 monthly. Strategy nifty500|lb63|top10|M|dual. First trading day of month." | Out-Null
Write-Host "Registered $Name Mon-Fri 09:30 (email only on first trading day of month)"
Write-Host ""
Write-Host "Dry run (no email):"
Write-Host "  powershell -File `"$Runner`" -NoEmail -Force"
Write-Host "Send now:"
Write-Host "  powershell -File `"$Runner`" -Force"
