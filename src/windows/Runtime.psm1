<#
@module Runtime
@description The protected copy that elevated and SYSTEM tasks run from (security review
2026-10-29, M-1): %ProgramFiles%\RTX40 Ka-chow!, writable only by Administrators and
SYSTEM, holding the scripts, the signed images, firmware, public certificate, a copy of a
PSF-signed Python, and the install's state (record and logs). Also locks a path to that ACL.
@output Get-RuntimeRoot, Test-InRuntime, Assert-InRuntime, Protect-AdminOnly,
        Copy-PythonRuntime, Install-Runtime, Remove-Runtime, Invoke-RuntimeCommand
@dependencies Project.psm1; icacls and robocopy (Windows); Install/Remove need elevation
#>
Set-StrictMode -Version 3
Import-Module (Join-Path $PSScriptRoot 'Project.psm1')

$script:RuntimeRoot = Join-Path $env:ProgramFiles 'RTX40 Ka-chow!'
$script:Admins = 'S-1-5-32-544'
$script:System = 'S-1-5-18'
$script:Users = 'S-1-5-32-545'

function Get-RuntimeRoot { $script:RuntimeRoot }

function Test-InRuntime {
    [IO.Path]::GetFullPath((Get-ProjectRoot)).TrimEnd('\') -eq [IO.Path]::GetFullPath($script:RuntimeRoot).TrimEnd('\')
}

# Tasks that run elevated or as SYSTEM must point at code no ordinary account can change.
function Assert-InRuntime {
    if (-not (Test-InRuntime)) { throw "Tasks are registered only from the protected copy in $script:RuntimeRoot; run kachow.ps1 install." }
}

# Owner Administrators, inheritance off, Administrators and SYSTEM full control, Users read
# and run (none with -NoRead); a directory's contents then inherit only that. Verified after.
function Protect-AdminOnly([Parameter(Mandatory)] [string]$Path, [switch]$NoRead) {
    $dir = Test-Path -LiteralPath $Path -PathType Container
    $inh = if ($dir) { '(OI)(CI)' } else { '' }
    $grants = @("*S-1-5-32-544:$($inh)F", "*S-1-5-18:$($inh)F")
    if (-not $NoRead) { $grants += "*S-1-5-32-545:$($inh)RX" }
    $allowed = @($script:Admins, $script:System) + $(if ($NoRead) { @() } else { @($script:Users) })
    & icacls $Path /setowner '*S-1-5-32-544' /C /Q | Out-Null
    if ($LASTEXITCODE) { throw "icacls could not make Administrators the owner of $Path" }
    & icacls $Path /inheritance:r /grant:r @grants /C /Q | Out-Null
    if ($LASTEXITCODE) { throw "icacls could not protect $Path" }
    foreach ($rule in (Get-Acl -LiteralPath $Path).Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($allowed -notcontains $sid) { & icacls $Path /remove:g "*$sid" /remove:d "*$sid" /C /Q | Out-Null }
    }
    if ($dir -and @(Get-ChildItem -LiteralPath $Path -Force).Count) {
        & icacls (Join-Path $Path '*') /reset /T /C /Q | Out-Null
        if ($LASTEXITCODE) { throw "icacls could not reset the ACLs under $Path" }
        & icacls $Path /setowner '*S-1-5-32-544' /T /C /Q | Out-Null
        if ($LASTEXITCODE) { throw "icacls could not make Administrators the owner under $Path" }
    }
    $acl = Get-Acl -LiteralPath $Path
    $owner = (New-Object Security.Principal.NTAccount $acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value
    $sids = @($acl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value })
    if (-not $acl.AreAccessRulesProtected -or $owner -ne $script:Admins -or @($sids | Where-Object { $allowed -notcontains $_ }).Count) {
        throw "$Path is not locked to Administrators and SYSTEM"
    }
}

function Copy-Tree([string]$From, [string]$To, [switch]$Mirror) {
    $mode = if ($Mirror) { '/MIR' } else { '/E' }
    & robocopy $From $To $mode /XD __pycache__ /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $From -> $To failed ($LASTEXITCODE)" }
}

# The Python on PATH, copied without site-packages, tests or tools, once python.exe and its
# DLLs prove to be signed by the Python Software Foundation.
function Copy-PythonRuntime([Parameter(Mandatory)] [string]$Destination) {
    $exe = (Get-Command python -ErrorAction Stop).Source
    if ($exe -like '*\WindowsApps\*') { throw "python resolves to the Microsoft Store alias ($exe)." }
    $pyHome = Split-Path $exe
    foreach ($f in @($exe) + @(Get-ChildItem $pyHome -Filter 'python3*.dll' | ForEach-Object FullName)) {
        $sig = Get-AuthenticodeSignature -FilePath $f
        if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw "$f is not signed by the Python Software Foundation (status $($sig.Status))."
        }
    }
    $skip = @('Lib\site-packages', 'Lib\test', 'Lib\idlelib', 'Lib\tkinter', 'Lib\ensurepip', 'Doc', 'Tools', 'Scripts', 'include', 'libs', 'tcl') |
        ForEach-Object { Join-Path $pyHome $_ }
    & robocopy $pyHome $Destination /MIR /XD @skip __pycache__ /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy of Python failed ($LASTEXITCODE)" }
    $prefix = & (Join-Path $Destination 'python.exe') -I -c 'import sys; print(sys.prefix)'
    if ([IO.Path]::GetFullPath("$prefix").TrimEnd('\') -ne [IO.Path]::GetFullPath($Destination).TrimEnd('\')) {
        throw "The copied Python does not run from $Destination (prefix $prefix)."
    }
}

# Refreshes the protected copy from this repository and returns its root. The install's
# state moves into it once; from then on the copy owns it.
function Install-Runtime {
    if (Test-InRuntime) { throw 'Install-Runtime runs from the repository, not from the protected copy.' }
    $src = Get-ProjectRoot
    $dst = $script:RuntimeRoot
    $local = Join-Path $dst 'local'
    New-Item -ItemType Directory -Force $dst | Out-Null
    Protect-AdminOnly $dst
    foreach ($d in 'bin', 'src', 'config', 'third_party') { Copy-Tree (Join-Path $src $d) (Join-Path $dst $d) -Mirror }
    Copy-Tree (Get-LocalPath 'build\signed') (Join-Path $local 'build\signed') -Mirror
    Copy-Tree (Get-LocalPath 'efi') (Join-Path $local 'efi') -Mirror
    Copy-Tree (Get-LocalPath 'assets') (Join-Path $local 'assets') -Mirror
    New-Item -ItemType Directory -Force (Join-Path $local 'keys') | Out-Null
    Copy-Item (Get-LocalPath 'keys\MOK.cer') (Join-Path $local 'keys\MOK.cer') -Force
    foreach ($f in 'install-record.json', 'mok-enrolled.json') {
        $from = Get-LocalPath $f
        if ((Test-Path $from) -and -not (Test-Path (Join-Path $local $f))) { Copy-Item $from (Join-Path $local $f) }
    }
    $record = Get-LocalPath 'install-record.json'
    if (Test-Path $record) {
        New-Item -ItemType Directory -Force (Get-LocalPath 'backups') | Out-Null
        Move-Item $record (Get-LocalPath ('backups\install-record-moved-{0}.json' -f (Get-Date -Format 'yyyyMMdd-HHmmss')))
    }
    if ((Test-Path (Get-LocalPath 'logs')) -and -not (Test-Path (Join-Path $local 'logs'))) { Copy-Tree (Get-LocalPath 'logs') (Join-Path $local 'logs') }
    Copy-PythonRuntime (Join-Path $dst 'python')
    Protect-AdminOnly $dst
    $dst
}

# Keeps the copy's logs and backups in this repository's local\, then deletes the copy.
function Remove-Runtime {
    $dst = $script:RuntimeRoot
    if (-not (Test-Path $dst)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    foreach ($d in 'logs', 'backups') {
        $from = Join-Path $dst "local\$d"
        if (Test-Path $from) { Copy-Tree $from (Get-LocalPath "$d\runtime-$stamp") }
    }
    Remove-Item -LiteralPath $dst -Recurse -Force
}

# Runs `kachow.ps1 <Command>` from the protected copy in this console; returns its exit code.
function Invoke-RuntimeCommand([Parameter(Mandatory)] [string]$Command, [switch]$Yes, [string]$Password = 'tensor') {
    $script = Join-Path $script:RuntimeRoot 'bin\kachow.ps1'
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script, $Command, '-Password', $Password)
    if ($Yes) { $argList += '-Yes' }
    & powershell.exe @argList | Out-Host
    $LASTEXITCODE
}

Export-ModuleMember -Function Get-RuntimeRoot, Test-InRuntime, Assert-InRuntime, Protect-AdminOnly,
    Copy-PythonRuntime, Install-Runtime, Remove-Runtime, Invoke-RuntimeCommand
