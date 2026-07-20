$ErrorActionPreference = "Stop"

$taskName = "Congress Monitor Twice Daily"
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $projectDir "run_scheduled.bat"

if (-not (Test-Path -LiteralPath $runner)) {
    throw "Scheduled runner not found: $runner"
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\cmd.exe" `
    -Argument ('/d /c call "{0}"' -f $runner) `
    -WorkingDirectory $projectDir
$triggers = @(
    New-ScheduledTaskTrigger -Daily -At "00:00"
    New-ScheduledTaskTrigger -Daily -At "12:00"
)
$principal = New-ScheduledTaskPrincipal `
    -UserId $identity `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

$task = New-ScheduledTask `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Description "Runs Congress Monitor every day at midnight and noon."

Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null

$taskQuery = & "$env:SystemRoot\System32\schtasks.exe" /Query /TN $taskName /V /FO LIST
if ($LASTEXITCODE -ne 0) {
    throw "The task was registered but could not be verified."
}
Write-Host "Installed task: $taskName"
Write-Host "Run as: $identity"
Write-Host "Runner: $runner"
Write-Host $taskQuery
