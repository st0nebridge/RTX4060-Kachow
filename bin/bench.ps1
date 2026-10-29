#Requires -Version 5.1
<#
.SYNOPSIS
  Is the unlock active right now? Times 8192^3 GEMMs per tensor mode and reports the ratio
  of FP32-accumulate to FP16-accumulate (UNLOCKED above 0.8).
.DESCRIPTION
  Needs a Python with torch 2.7+ and CUDA; by default local\.venv-bench (README: Benchmark).
  Each run is saved to local\results\bench-<timestamp>.txt. Exit 0 when UNLOCKED.
.EXAMPLE
  .\bench.ps1
  .\bench.ps1 -Python C:\path\to\venv\Scripts\python.exe
#>
[CmdletBinding()]
param([string]$Python, [int]$Size = 8192, [int]$Iters = 50, [int]$Rounds = 3)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Project.psm1') -Force

if (-not $Python) { $Python = Get-LocalPath '.venv-bench\Scripts\python.exe' }
if (-not (Test-Path $Python)) { throw "No benchmark Python at $Python (README: Benchmark)" }
$results = Get-LocalPath 'results'
New-Item -ItemType Directory -Force $results | Out-Null
$out = Join-Path $results ('bench-{0}.txt' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

$entry = Join-Path (Get-ProjectRoot) 'bin\kachow.py'
$lines = & $Python -I -W ignore $entry bench --size $Size --iters $Iters --rounds $Rounds
$code = $LASTEXITCODE
$lines | Set-Content $out -Encoding utf8
$lines | ForEach-Object { Write-Host $_ }
Write-Host "Saved: $out"
exit $code
