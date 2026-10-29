#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Show the unlocker's latest boot log from the ESP and say whether that boot unlocked.
.DESCRIPTION
  Copies \GPU4090-UNLOCK\RUNnnnn.TXT (the newest, or -Name) to local\logs\ and prints it,
  followed by a one-line summary. Exit 0 for an unlocked or dryrun boot, 1 otherwise.
  The log proves the state when Windows started; bench.ps1 proves it now.
.EXAMPLE
  .\read-log.ps1
  .\read-log.ps1 -Name RUN0018.TXT
#>
[CmdletBinding()]
param([string]$Name)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Project.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Esp.psm1') -Force

$logs = Get-LocalPath 'logs'
New-Item -ItemType Directory -Force $logs | Out-Null
$copy = Invoke-WithEsp {
    param($esp)
    $dir = Join-Path $esp 'GPU4090-UNLOCK'
    if (-not (Test-Path $dir)) { throw 'No \GPU4090-UNLOCK\ on the ESP: the unlocker has not run yet.' }
    $f = if ($Name) { Get-Item (Join-Path $dir $Name) }
         else { Get-ChildItem $dir -Filter 'RUN*.TXT' | Sort-Object Name | Select-Object -Last 1 }
    if (-not $f) { throw "No RUN*.TXT in $dir" }
    Copy-Item $f.FullName (Join-Path $logs $f.Name) -Force
    Join-Path $logs $f.Name
} | Select-Object -Last 1

Write-Host "=== $copy"
Get-Content $copy | ForEach-Object { Write-Host $_ }
$code = Invoke-Kachow -Arguments @('runlog', $copy) -AllowFailure
exit $code
