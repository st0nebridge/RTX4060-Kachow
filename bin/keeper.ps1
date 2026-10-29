#Requires -Version 5.1
<#
.SYNOPSIS
  Keeps the RTX powered so the unlock lasts in hybrid mode. Run by the
  "RTX40 Ka-chow! keeper" task at startup (Register-KeeperTask, src\windows\Machine.psm1).
.DESCRIPTION
  Appends this boot, the uptime and the RTX's power state to local\logs\keeper.log, then
  runs `kachow keep`, which holds a CUDA context on the RTX until the machine shuts down.
  RTX=D3 on that line means the RTX was off before the keeper started, and the unlock may
  have been reset (not always: RUN0029 started at D3 and stayed unlocked); bench.ps1 says.
.EXAMPLE
  .\keeper.ps1 -Python C:\path\to\python.exe
#>
[CmdletBinding()]
param([Parameter(Mandatory)] [string]$Python)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Project.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Machine.psm1') -Force

$log = Get-LocalPath 'logs\keeper.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$now = Get-Date
$line = '{0:HH:mm:ss} start boot={1:o} uptime={2:F0}s RTX={3}' -f $now, $boot, ($now - $boot).TotalSeconds, (Get-RtxPowerState)
Add-Content -Path $log -Value $line -Encoding utf8
& $Python -I (Join-Path $PSScriptRoot 'kachow.py') 'keep', '--log', $log
exit $LASTEXITCODE
