#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Show config\banner.txt on the unlocker's start screen (no rebuild or re-signing).
.DESCRIPTION
  Edit config\banner.txt (UTF-8, at most 20 lines of 79 columns), then run this. It
  encodes the art, copies it to the ESP's \GPU4090-ASSETS\ and prints the ASCII copy the
  unlocker falls back to when the firmware font lacks a glyph. Delete config\banner.txt
  and run it again to show no banner.
.EXAMPLE
  .\bin\banner.ps1
#>
[CmdletBinding()]
param([string]$Art)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Esp.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Banner.psm1') -Force

$extra = @{}
if ($Art) { $extra.Art = (Resolve-Path $Art).Path }
Invoke-WithEsp { param($esp) Install-EspBanner -Esp $esp @extra }
