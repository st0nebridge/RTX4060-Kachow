#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Set or remove the NVIDIA driver value RMForceRtd3D3Hot (runtime power-off as D3hot).
.DESCRIPTION
  Tried on 2026-10-28 to keep the volatile unlock through hybrid-mode idle power-off; it
  did not (fp16_acc32 ratio 0.62) and was removed. Kept for the record and for retests.
  Sets RMForceRtd3D3Hot=1 (DWORD) on the RTX's display-class driver key after exporting
  the key to local\backups\. The value name comes from nvlddmkm.sys; NVIDIA does not
  document it. Takes effect on the next boot.
.EXAMPLE
  .\d3hot.ps1 -Remove
#>
[CmdletBinding()]
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Project.psm1') -Force

$dev = @(Get-PnpDevice -Class Display | Where-Object { $_.InstanceId -like 'PCI\VEN_10DE&DEV_28A0*' })
if ($dev.Count -ne 1) { throw "Expected one RTX 4060 Laptop GPU, found $($dev.Count)" }
$drv = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Enum\$($dev[0].InstanceId)").Driver
$key = "HKLM:\SYSTEM\CurrentControlSet\Control\Class\$drv"
$regKey = "HKLM\SYSTEM\CurrentControlSet\Control\Class\$drv"
Write-Host "NVIDIA driver key: $regKey"

$backupDir = Get-LocalPath 'backups'
New-Item -ItemType Directory -Force $backupDir | Out-Null
$backup = Join-Path $backupDir ('nvidia-class-key-{0}.reg' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
& reg.exe export $regKey $backup /y | Out-Null
if ($LASTEXITCODE) { throw 'reg export failed' }
Write-Host "Backup: $backup"

if ($Remove) {
    Remove-ItemProperty -Path $key -Name RMForceRtd3D3Hot -ErrorAction SilentlyContinue
} else {
    New-ItemProperty -Path $key -Name RMForceRtd3D3Hot -PropertyType DWord -Value 1 -Force | Out-Null
}
$v = (Get-ItemProperty $key).PSObject.Properties['RMForceRtd3D3Hot']
Write-Host "Read back: RMForceRtd3D3Hot = $(if ($v) { $v.Value } else { '(not set)' }). Takes effect on the next boot."
