$TaskName = "SolarChargeScheduler"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetBatch = Join-Path $ScriptDir "run.bat"

# Verify file exists
if (-not (Test-Path $TargetBatch)) {
    Write-Error "Could not find run.bat at $TargetBatch"
    exit 1
}

Write-Host "Configuring task: $TaskName"
Write-Host "Target script: $TargetBatch"
Write-Host "Time: 7:00 PM daily"

# Register the scheduled task using schtasks.exe (high compatibility, works under standard user context)
# We enclose the path in double quotes to handle any spaces (like "OneDrive")
$triggerPath = "`"$TargetBatch`""
$cmd = "schtasks /create /tn `"$TaskName`" /tr `"$triggerPath`" /sc daily /st 19:00 /f"

Write-Host "Running command: $cmd"
Invoke-Expression $cmd

if ($LASTEXITCODE -eq 0) {
    Write-Host -ForegroundColor Green "Successfully scheduled the solar optimizer agent to run daily at 7 PM."
} else {
    Write-Error "Failed to schedule the task. Please verify you have permissions to run schtasks."
}
