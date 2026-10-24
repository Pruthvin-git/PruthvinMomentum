# K-5 bi-weekly Friday mail — Alpha + Microcap + Midcap Momentum (20:30 IST)
param(
    [string]$EmailTo = "pruthvin98@gmail.com",
    [string[]]$ExtraArgs = @()
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$workspaceRoot = Split-Path -Parent $ScriptDir

$smtpFallbacks = @(
    (Join-Path $ScriptDir "smtp_config.ps1"),
    (Join-Path $workspaceRoot "new_logic\smtp_config.ps1"),
    (Join-Path $workspaceRoot "Hourly_Momentum\smtp_config.ps1"),
    (Join-Path $workspaceRoot "Ultimate_Momentum\smtp_config.ps1")
)
foreach ($path in $smtpFallbacks) {
    if (Test-Path $path) {
        . $path
        if ($path -ne (Join-Path $ScriptDir "smtp_config.ps1")) { Write-Host "Using SMTP config: $path" }
        break
    }
}
if ([string]::IsNullOrWhiteSpace($SmtpUser) -or [string]::IsNullOrWhiteSpace($SmtpPassword)) {
    Write-Error "Set SmtpUser and SmtpPassword in smtp_config.ps1"
}

$env:SMTP_USER = $SmtpUser
$env:SMTP_PASSWORD = $SmtpPassword
$env:SMTP_HOST = if ($SmtpHost) { $SmtpHost } else { "smtp.gmail.com" }
$env:SMTP_PORT = if ($SmtpPort) { "$SmtpPort" } else { "465" }
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
if ($EmailTo) { $env:HOURLY_MOM_EMAIL_TO = $EmailTo }

$LogDir = Join-Path $ScriptDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("k5_2w_combined_mail_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))

$PythonCandidates = @(
    "C:\Users\pruthvir\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\pruthvir\AppData\Local\Programs\Python\Python312\python.exe"
)
$Python = [string]($PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Python) { $Python = [string](Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Write-Error "Python not found" }

$RunScript = Join-Path $ScriptDir "k5_2w_combined_mail.py"

function Invoke-PythonLogged {
    param([Parameter(Mandatory = $true)][string[]]$CommandArgs)
    $preview = "$Python " + ($CommandArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }) -join ' '
    "=== RUN $preview ===" | Tee-Object -FilePath $LogFile -Append | Out-Null
    $proc = Start-Process -FilePath $Python -ArgumentList $CommandArgs -WorkingDirectory $ScriptDir `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput ($LogFile + ".out") -RedirectStandardError ($LogFile + ".err")
    if (Test-Path ($LogFile + ".out")) { Get-Content ($LogFile + ".out") | Tee-Object -FilePath $LogFile -Append | Out-Null }
    if (Test-Path ($LogFile + ".err")) { Get-Content ($LogFile + ".err") | Tee-Object -FilePath $LogFile -Append | Out-Null }
    Remove-Item ($LogFile + ".out"), ($LogFile + ".err") -ErrorAction SilentlyContinue
    "=== EXIT $($proc.ExitCode) ===" | Tee-Object -FilePath $LogFile -Append | Out-Null
    return [int]$proc.ExitCode
}

try {
    $runArgs = @($RunScript, "--email-to", $EmailTo) + $ExtraArgs
    $code = Invoke-PythonLogged -CommandArgs $runArgs
    exit $code
} catch {
    $_ | Out-String | Tee-Object -FilePath $LogFile -Append
    exit 1
}
