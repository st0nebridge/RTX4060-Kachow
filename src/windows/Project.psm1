<#
@module Project
@description Project paths and the bridge to the Python tools (bin/kachow.py).
@output Get-ProjectRoot, Get-LocalPath, Invoke-Kachow, Read-InstallRecord, Write-InstallRecord
@dependencies python 3.11+: the copy's python\python.exe, else the one on PATH
#>
Set-StrictMode -Version 3

$script:Root = Split-Path (Split-Path $PSScriptRoot)

function Get-ProjectRoot { $script:Root }

# local/ holds machine state that never enters git: keys, firmware, EFI images, records.
function Get-LocalPath([string]$Child = '') {
    $p = Join-Path $script:Root 'local'
    if ($Child) { $p = Join-Path $p $Child }
    $p
}

# Runs `python -I bin/kachow.py @Arguments`; throws on a non-zero exit unless -AllowFailure.
# Prints the output and returns the exit code, or with -Capture returns the output lines.
# The protected copy uses its own python\python.exe; the repository uses the one on PATH.
function Invoke-Kachow {
    param([Parameter(Mandatory)] [string[]]$Arguments, [switch]$AllowFailure, [switch]$Capture)
    $entry = Join-Path $script:Root 'bin\kachow.py'
    $python = Join-Path $script:Root 'python\python.exe'
    if (-not (Test-Path $python)) { $python = 'python' }
    $out = & $python -I $entry @Arguments
    $code = $LASTEXITCODE
    if (-not $Capture) { $out | ForEach-Object { Write-Host $_ } }
    if ($code -and -not $AllowFailure) { throw "kachow $($Arguments[0]) failed (exit $code)" }
    if ($Capture) { return , @($out) }
    $code
}

function Read-InstallRecord {
    $path = Get-LocalPath 'install-record.json'
    if (-not (Test-Path $path)) { return $null }
    Get-Content $path -Raw | ConvertFrom-Json
}

function Write-InstallRecord([Parameter(Mandatory)] [hashtable]$Record) {
    $path = Get-LocalPath 'install-record.json'
    New-Item -ItemType Directory -Force (Split-Path $path) | Out-Null
    $Record | ConvertTo-Json | Set-Content $path -Encoding utf8
    $path
}

Export-ModuleMember -Function Get-ProjectRoot, Get-LocalPath, Invoke-Kachow, Read-InstallRecord, Write-InstallRecord
