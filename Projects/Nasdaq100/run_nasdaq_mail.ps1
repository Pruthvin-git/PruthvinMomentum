# Nasdaq monthly momentum mail (first US trading day of month; 09:30 IST task)
param(
    [string]$EmailTo = "pruthvin98@gmail.com",
    [string[]]$ExtraArgs = @(),
    [switch]$NoEmail,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir
$workspaceRoot = Split-Path -Parent $ScriptDir

$smtpFallbacks = @(
    (Join-Path $ScriptDir "smtp_config.ps1"),
    (Join-Path $workspaceRoot "Hourly_Momentum\smtp_config.ps1"),
    (Join-Path $workspaceRoot "new_logic\smtp_config.ps1"),
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
    Write-Error "Set SmtpUser and SmtpPassword in smtp_config.ps1 (copy from Hourly_Momentum if needed)"
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
$LogFile = Join-Path $LogDir ("nasdaq_mail_{0}.log" -f (Get-Date -Format "yyyy-MM-dd_HHmm"))

$PythonCandidates = @(
    "C:\Users\pruthvir\AppData\Local\Programs\Python\Python313\python.exe",
    "C:\Users\pruthvir\AppData\Local\Programs\Python\Python312\python.exe"
)
$Python = [string]($PythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1)
if (-not $Python) { $Python = [string](Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $Python) { Write-Error "Python not found" }

$RunScript = Join-Path $ScriptDir "nasdaq.py"

try {
    $pyArgs = [System.Collections.Generic.List[string]]::new()
    if ($NoEmail) { $pyArgs.Add("--no-email") }
    if ($Force) { $pyArgs.Add("--force") }
    foreach ($a in @($ExtraArgs)) {
        if ($a) { $pyArgs.Add([string]$a) }
    }
    $preview = "$Python $RunScript" + $(if ($pyArgs.Count) { " " + ($pyArgs -join " ") } else { "" })
    "=== RUN $preview ===" | Tee-Object -FilePath $LogFile -Append | Out-Null
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $invoke = @($RunScript) + @($pyArgs.ToArray())
    & $Python @invoke 2>&1 | Tee-Object -FilePath $LogFile -Append
    $ErrorActionPreference = $prevEap
    $code = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    "=== EXIT $code ===" | Tee-Object -FilePath $LogFile -Append | Out-Null
    exit $code
} catch {
    $_ | Out-String | Tee-Object -FilePath $LogFile -Append
    exit 1
}
