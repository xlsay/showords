param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("server", "client")]
    [string]$Role
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$appDir = Join-Path $repoRoot "codes\$Role"

Write-Host "==> Installing MeetingAssist $Role..."

# Find Python 3.12+
$systemPython = $null
$systemPythonArgs = @()
$null = cmd /c "py -3.12 -c ""import sys; assert sys.version_info >= (3, 12)"" >nul 2>nul" 2>$null
if ($LASTEXITCODE -eq 0) {
    $systemPython = "py"
    $systemPythonArgs = @("-3.12")
}
if (-not $systemPython) {
    $null = cmd /c "python -c ""import sys; assert sys.version_info >= (3, 12)"" >nul 2>nul" 2>$null
    if ($LASTEXITCODE -eq 0) { $systemPython = "python" }
}
if (-not $systemPython) {
    Write-Host "Error: Python 3.12+ is required but not found."
    exit 1
}
Write-Host "Using Python interpreter: $systemPython $systemPythonArgs"

if ($Role -eq "client") {
    try { $null = Get-Command npm -ErrorAction Stop }
    catch {
        Write-Host "Error: npm not found. Please install Node.js 20+ and try again."
        exit 1
    }
}

# Python environment
Set-Location $appDir
if (-not (Test-Path ".venv")) {
    & $systemPython @systemPythonArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
$venvPython = Join-Path $appDir ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if ($Role -eq "client") {
    $frontendDir = Join-Path $appDir "frontend"
    Set-Location $frontendDir
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }

    # npm 11 withholds Electron's download script, and electron@33 can extract partially on Node 26.
    $electronDir = Join-Path $frontendDir "node_modules\electron"
    if (-not (Test-Path (Join-Path $electronDir "path.txt"))) {
        Write-Host "==> Fetching the Electron binary..."
        node (Join-Path $electronDir "install.js")
    }
    if (-not (Test-Path (Join-Path $electronDir "dist\electron.exe"))) {
        $zip = Get-ChildItem -Recurse "$env:LOCALAPPDATA\electron\Cache" -Filter "electron-*-win32-*.zip" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $zip) { throw "Electron binary download failed" }
        Remove-Item -Recurse -Force (Join-Path $electronDir "dist") -ErrorAction SilentlyContinue
        Expand-Archive -Path $zip.FullName -DestinationPath (Join-Path $electronDir "dist") -Force
        Set-Content -Path (Join-Path $electronDir "path.txt") -Value "electron.exe" -NoNewline -Encoding ascii
    }
}

Write-Host ""
Write-Host "Installation complete. Start with:"
Write-Host "  .\scripts\start.ps1 -Role $Role"
