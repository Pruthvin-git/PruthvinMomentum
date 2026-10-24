# Install Task Scheduler — K-5 bi-weekly Friday mail at 20:30 IST.
# One email: Alpha 50 + Microcap 250 + Midcap Momentum 50.
# Fires every Friday; the Python script sends only on even W-FRI weeks.
param([string]$EmailTo = "pruthvin98@gmail.com")

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runner = Join-Path $ScriptDir "run_alpha50_top5_2w_mail.ps1"
if (-not (Test-Path $Runner)) { Write-Error "Missing $Runner" }

foreach ($old in @(
        "AlphaMom_Alpha50_Top5_2W_Friday",
        "AlphaMom_Microcap250_Top5_2W_Friday",
        "AlphaMom_K5_2W_Friday"
    )) {
    $existing = Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $old -Confirm:$false
        Write-Host "Removed existing task $old"
    }
}

$Name = "AlphaMom_K5_2W_Friday"
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -EmailTo `"$EmailTo`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ScriptDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "20:30"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings `
    -Description "K-5 21-day ROC dual-mom bi-weekly: Alpha 50 + Microcap 250 + Midcap Momentum 50. Even-week Fridays 20:30 IST." | Out-Null
Write-Host "Registered $Name every Friday 20:30 (script skips odd weeks)"
Write-Host ""
Write-Host "Test (no email):"
Write-Host "  powershell -File `"$Runner`" -ExtraArgs @('--no-email','--force')"
Write-Host "Send now:"
Write-Host "  powershell -File `"$Runner`" -ExtraArgs @('--force')"
