# Combined K-5 mail is installed by install_alpha50_top5_2w_mail_task.ps1.
# This file remains so the previous Microcap installer path still works.
param([string]$EmailTo = "pruthvin98@gmail.com")
& (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "install_alpha50_top5_2w_mail_task.ps1") -EmailTo $EmailTo
