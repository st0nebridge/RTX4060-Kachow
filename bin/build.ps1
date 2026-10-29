#Requires -Version 5.1
<#
.SYNOPSIS
  Build gate: patched unlocker images from pinned source, hash-checked, .sbat added, MOK-signed.
.DESCRIPTION
  1. Clones local/upstream at the commit pinned in third_party/manifest.json into
     local/build/src and applies the manifest's patches in order (patches/*.patch).
  2. Compiles the variants with zig 0.14.1 (kachow build).
  3. Compares each image with the hardware-verified hash in the manifest; a mismatch fails
     unless -AcceptNewHashes (use only after an intended source change, then re-pin).
  4. Adds .sbat and signs with local/keys/MOK.pfx into local/build/signed/<id>-grubx64.efi,
     then verifies each signature. -NoSign stops after step 3. Signing needs an elevated
     session: the key files are readable by Administrators and SYSTEM only.
.EXAMPLE
  .\bin\build.ps1
  .\bin\build.ps1 -Variants UNLOCK4090 -NoSign
#>
[CmdletBinding()]
param(
    [ValidateSet('UNLOCK4090', 'UNLOCK4090M', 'DRYRUN4090', 'RELTEST4090')]
    [string[]]$Variants = @('UNLOCK4090', 'UNLOCK4090M', 'DRYRUN4090', 'RELTEST4090'),
    [switch]$NoSign,
    [switch]$AcceptNewHashes
)
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Project.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '..\src\windows\Signing.psm1') -Force

$root = Get-ProjectRoot
$manifest = Get-Content (Join-Path $root 'third_party\manifest.json') -Raw | ConvertFrom-Json
$commit = $manifest.upstream.commit
$upstream = Get-LocalPath 'upstream'
$zig = Get-LocalPath $manifest.toolchain.zig.path
$work = Get-LocalPath 'build'
$src = Join-Path $work 'src'
$out = Join-Path $work 'out'
$signed = Join-Path $work 'signed'
$ids = @{ UNLOCK4090 = 'auto'; UNLOCK4090M = 'manual'; DRYRUN4090 = 'dryrun'; RELTEST4090 = 'reltest' }

if (-not (Test-Path (Join-Path $upstream '.git'))) { throw "No upstream checkout at $upstream (see README: Setting up local/)" }
if (-not (Test-Path $zig)) { throw "zig not found at $zig" }

Write-Host "== Source: upstream $commit + $($manifest.upstream.patches -join ', ')"
if (Test-Path $src) { Remove-Item $src -Recurse -Force }
& git clone -q --no-checkout $upstream $src
if ($LASTEXITCODE) { throw 'git clone failed' }
& git -C $src -c core.autocrlf=false -c advice.detachedHead=false checkout -q $commit
if ($LASTEXITCODE) { throw "pinned commit $commit not in $upstream" }
foreach ($patch in $manifest.upstream.patches) {
    & git -C $src apply (Join-Path $root $patch)
    if ($LASTEXITCODE) { throw "$patch does not apply to the pinned upstream commit" }
}

Write-Host "== Compile: $($Variants -join ', ')"
if (Test-Path $out) { Remove-Item $out -Recurse -Force }
$null = Invoke-Kachow -Arguments (@('build', $src, $zig, $out) + $Variants)

Write-Host '== Hashes vs hardware-verified builds'
$code = Invoke-Kachow -Arguments (@('verify', '--builds', $out) + $Variants) -AllowFailure
if ($code -and -not $AcceptNewHashes) { throw 'Built image differs from the hardware-verified build (see MISMATCH above)' }

if ($NoSign) { Write-Host 'BUILD GATE: PASSED (unsigned)' -ForegroundColor Green; exit 0 }

# The private key is readable by Administrators and SYSTEM only (security review H-1).
$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Signing reads the admin-only MOK key: run build.ps1 from an elevated PowerShell, or use -NoSign.'
}
Protect-SigningKey

Write-Host '== .sbat + MOK signature'
New-Item -ItemType Directory -Force $signed | Out-Null
foreach ($v in $Variants) {
    $dst = Join-Path $signed "$($ids[$v])-grubx64.efi"
    $null = Invoke-Kachow -Arguments @('sbat', (Join-Path $out "$v.EFI"), $dst)
    Set-MokSignature $dst
    Write-Host "  signed: $dst"
}
Write-Host 'BUILD GATE: PASSED' -ForegroundColor Green
