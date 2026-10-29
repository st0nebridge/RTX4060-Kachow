#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Swap the unlocker variant on an installed ESP (\EFI\tensor-unlock\grubx64.efi).
.DESCRIPTION
  Refuses any image that is not MOK-signed with .sbat (an unsigned grubx64.efi makes shim
  stop with "Security Violation"), copies it, compares hashes, refreshes the start-screen
  banner from config\banner.txt, suspends BitLocker for the next boots and records the new
  mode in local\install-record.json. Install with kachow.ps1 install first.
.EXAMPLE
  .\deploy.ps1 -Variant dryrun
  .\deploy.ps1 -Variant auto
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('auto', 'manual', 'dryrun', 'reltest')] [string]$Variant,
    [int]$RebootCount = 2
)
$ErrorActionPreference = 'Stop'
foreach ($m in 'Project', 'Esp', 'Install', 'Machine') {
    Import-Module (Join-Path $PSScriptRoot "..\src\windows\$m.psm1") -Force
}

Invoke-WithEsp {
    param($esp)
    Set-EspUnlocker -Esp $esp -Variant $Variant
    Write-Host "ESP grubx64.efi = $Variant (MOK-signed, hash verified)"
}
if (Suspend-BitLockerForBoots $RebootCount) { Write-Host "BitLocker suspended for $RebootCount boots" }

$rec = Read-InstallRecord
if ($rec) {
    $h = @{}
    $rec.PSObject.Properties | ForEach-Object { $h[$_.Name] = $_.Value }
    $h.mode = $Variant
    $null = Write-InstallRecord $h
}
