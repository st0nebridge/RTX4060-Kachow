<#
@module Signing
@description Sign EFI images with the MOK and refuse any image that is not MOK-signed
with .sbat. Two independent checks: Windows' Authenticode signer thumbprint and the
Python signature/.sbat check (kachow check-signed). Verification reads only the public
MOK.cer; the private key (MOK.key, MOK.pfx) is readable by Administrators and SYSTEM only,
so signing needs an elevated session (security review 2026-10-29, H-1).
@output Get-MokCertificate, Get-MokSigningCertificate, Protect-SigningKey, Set-MokSignature,
        Assert-MokSigned
@dependencies Project.psm1, Runtime.psm1; local/keys/MOK.cer, and MOK.pfx (no password) to sign
#>
Set-StrictMode -Version 3
Import-Module (Join-Path $PSScriptRoot 'Project.psm1')
Import-Module (Join-Path $PSScriptRoot 'Runtime.psm1')

# The MOK certificate (public part only).
function Get-MokCertificate {
    $cer = Get-LocalPath 'keys\MOK.cer'
    if (-not (Test-Path $cer)) { throw "MOK.cer not found at $cer" }
    [Security.Cryptography.X509Certificates.X509Certificate2]::new($cer)
}

# The certificate with its private key, for signing; readable only in an elevated session.
function Get-MokSigningCertificate {
    $pfx = Get-LocalPath 'keys\MOK.pfx'
    if (-not (Test-Path $pfx)) { throw "MOK.pfx not found at $pfx" }
    try { [Security.Cryptography.X509Certificates.X509Certificate2]::new($pfx, '', 'Exportable') }
    catch { throw "Cannot read ${pfx}: signing needs an elevated session (the key is admin-only). $($_.Exception.Message)" }
}

# MOK.key and MOK.pfx readable and writable by Administrators and SYSTEM only.
function Protect-SigningKey {
    foreach ($f in 'MOK.key', 'MOK.pfx') {
        $p = Get-LocalPath "keys\$f"
        if (Test-Path $p) { Protect-AdminOnly $p -NoRead }
    }
}

# Throws unless $Path is Authenticode-signed by the MOK and carries .sbat.
# Self-signed, so Windows reports UnknownError; only the signer identity matters to shim.
function Assert-MokSigned([Parameter(Mandatory)] [string]$Path) {
    $cert = Get-MokCertificate
    $sig = Get-AuthenticodeSignature -FilePath $Path
    if ($sig.Status -eq 'NotSigned' -or $null -eq $sig.SignerCertificate -or
        $sig.SignerCertificate.Thumbprint -ne $cert.Thumbprint) {
        throw "$Path is not signed with the MOK (status $($sig.Status))"
    }
    $code = Invoke-Kachow -Arguments @('check-signed', $Path, '--cert', (Get-LocalPath 'keys\MOK.cer')) -AllowFailure
    if ($code) { throw "$Path failed the MOK/.sbat check" }
}

# Signs $Path in place with SHA-256, then verifies it.
function Set-MokSignature([Parameter(Mandatory)] [string]$Path) {
    $null = Set-AuthenticodeSignature -FilePath $Path -Certificate (Get-MokSigningCertificate) -HashAlgorithm SHA256
    Assert-MokSigned $Path
}

Export-ModuleMember -Function Get-MokCertificate, Get-MokSigningCertificate, Protect-SigningKey, Set-MokSignature, Assert-MokSigned
