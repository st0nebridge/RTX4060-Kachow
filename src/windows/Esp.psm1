<#
@module Esp
@description Mount the EFI System Partition on a free drive letter, run work against it,
and always dismount it again.
@output Get-FreeDriveLetter, Invoke-WithEsp
@dependencies mountvol.exe; Invoke-WithEsp needs an elevated session
#>
Set-StrictMode -Version 3

$script:Candidates = [char[]]'ZYXWVUTSRQPONMLKJIHGFED'

# First candidate letter (Z downwards) not in -Used; $null when all are taken.
function Get-FreeDriveLetter {
    param([string[]]$Used = @((Get-Volume | Where-Object { $_.DriveLetter }).DriveLetter))
    foreach ($l in $script:Candidates) {
        if ($Used -notcontains [string]$l) { return [string]$l }
    }
    $null
}

# Mounts the ESP, calls $Action with its root (e.g. 'Z:\'), dismounts in all cases.
function Invoke-WithEsp {
    param([Parameter(Mandatory)] [scriptblock]$Action)
    $letter = Get-FreeDriveLetter
    if (-not $letter) { throw 'No free drive letter for mounting the ESP.' }
    & mountvol "${letter}:" /s
    if ($LASTEXITCODE) { throw "mountvol /s failed (exit $LASTEXITCODE)" }
    try {
        & $Action "${letter}:\"
    } finally {
        & mountvol "${letter}:" /d
    }
}

Export-ModuleMember -Function Get-FreeDriveLetter, Invoke-WithEsp
