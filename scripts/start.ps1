param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("server", "client")]
    [string]$Role
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$appDir = Join-Path $repoRoot "codes\$Role"

$venvPython = Join-Path $appDir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Error: $Role environment not found. Run .\scripts\install.ps1 -Role $Role first."
    exit 1
}

if ($Role -eq "server") {
    Write-Host "==> Starting MeetingAssist server..."
    Set-Location $appDir
    & $venvPython main.py
    exit $LASTEXITCODE
}

# The desktop app starts and supervises the local capture bridge itself.
Write-Host "==> Starting MeetingAssist client..."
Set-Location (Join-Path $appDir "frontend")
npm run dev
exit $LASTEXITCODE
