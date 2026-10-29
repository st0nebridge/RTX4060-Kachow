#Requires -Version 5.1
<#
.SYNOPSIS
  Test gate: pytest with coverage over src/kachow, then a parse check of every PowerShell
  script and module, plus an optional lint script (-Preflight, or $env:KACHOW_PS_PREFLIGHT).
.DESCRIPTION
  Creates .venv from requirements-dev.txt on first use. Fails (exit 1) if any test fails,
  coverage drops below the floor, or a PowerShell file has a parse or preflight error.
.EXAMPLE
  .\bin\test.ps1
  .\bin\test.ps1 -CoverageFloor 90
#>
[CmdletBinding()]
param([int]$CoverageFloor = 85, [string]$Preflight = $env:KACHOW_PS_PREFLIGHT)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host 'Creating .venv ...'
    & python -m venv (Join-Path $root '.venv')
    & $py -m pip install -q -r (Join-Path $root 'requirements-dev.txt')
    if ($LASTEXITCODE) { Write-Error 'pip install failed'; exit 1 }
}

$failed = $false
Push-Location $root
try {
    & $py -m pytest --cov --cov-report=term-missing "--cov-fail-under=$CoverageFloor"
    if ($LASTEXITCODE) { $failed = $true }
} finally { Pop-Location }

$scripts = @(Get-ChildItem (Join-Path $root 'bin'), (Join-Path $root 'src\windows') -Include *.ps1, *.psm1 -Recurse)
foreach ($s in $scripts) {
    $tokens = $null; $errs = $null
    [void][Management.Automation.Language.Parser]::ParseFile($s.FullName, [ref]$tokens, [ref]$errs)
    foreach ($e in $errs) { Write-Host "$($s.Name):$($e.Extent.StartLineNumber): parse error: $($e.Message)"; $failed = $true }
}
if ($Preflight -and (Test-Path $Preflight)) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $Preflight @($scripts.FullName)
    if ($LASTEXITCODE) { $failed = $true }
    Write-Host "PowerShell lint: $($scripts.Count) files checked"
} else {
    Write-Host "Parse check only ($($scripts.Count) files); pass -Preflight <script> to lint them too"
}

if ($failed) { Write-Host 'TEST GATE: FAILED' -ForegroundColor Red; exit 1 }
Write-Host 'TEST GATE: PASSED' -ForegroundColor Green
