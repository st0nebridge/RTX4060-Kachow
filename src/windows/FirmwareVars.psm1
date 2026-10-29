<#
@module FirmwareVars
@description Read and write UEFI variables from Windows, parse EFI_LOAD_OPTION
(Boot####) entries, and arrange BootOrder and BootNext.
@output Enable-SystemEnvironmentPrivilege, Get-FirmwareVariable, Set-FirmwareVariable,
        ConvertFrom-LoadOption, Find-BootEntry, Clear-BootEntryOptionalData, Remove-BootEntry,
        Repair-BootEntry, ConvertFrom-BootOrder, ConvertTo-BootOrder, Move-BootNumber,
        Set-BootEntryPosition, Set-BootNext, Clear-BootNext, Get-BootCurrent
@dependencies kernel32/advapi32 (P/Invoke), bcdedit.exe (Repair-BootEntry); variable access needs an elevated session
        with SeSystemEnvironmentPrivilege, which is disabled by default even for admins
#>
Set-StrictMode -Version 3

$script:GlobalGuid = '{8be4df61-93ca-11d2-aa0d-00e098032b8c}'
$script:ShimGuid = '{605dab50-e046-4300-abb6-3dd810dd8b23}'

if (-not ('Kachow.Fw' -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
namespace Kachow {
public static class Fw {
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern bool SetFirmwareEnvironmentVariableExW(string n, string g, byte[] v, uint s, uint a);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    public static extern uint GetFirmwareEnvironmentVariableExW(string n, string g, byte[] v, uint s, out uint a);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool OpenProcessToken(IntPtr h, uint acc, out IntPtr tok);
    [DllImport("advapi32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    static extern bool LookupPrivilegeValueW(string sys, string name, out LUID luid);
    [DllImport("advapi32.dll", SetLastError=true)]
    static extern bool AdjustTokenPrivileges(IntPtr tok, bool dis, ref TOKEN_PRIVILEGES tp, uint len, IntPtr prev, IntPtr retLen);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [StructLayout(LayoutKind.Sequential)] struct LUID { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential, Pack=4)] struct TOKEN_PRIVILEGES { public uint Count; public LUID Luid; public uint Attr; }
    public static int EnablePrivilege() {
        IntPtr t; LUID l;
        if (!OpenProcessToken(GetCurrentProcess(), 0x28, out t)) return Marshal.GetLastWin32Error();
        if (!LookupPrivilegeValueW(null, "SeSystemEnvironmentPrivilege", out l)) return Marshal.GetLastWin32Error();
        var tp = new TOKEN_PRIVILEGES { Count = 1, Luid = l, Attr = 2 };
        AdjustTokenPrivileges(t, false, ref tp, (uint)Marshal.SizeOf(tp), IntPtr.Zero, IntPtr.Zero);
        return Marshal.GetLastWin32Error();
    }
}
}
"@
}

function Enable-SystemEnvironmentPrivilege {
    $e = [Kachow.Fw]::EnablePrivilege()
    if ($e -ne 0) { throw "Could not enable SeSystemEnvironmentPrivilege (error $e)" }
}

function Resolve-VendorGuid([string]$Vendor) {
    switch ($Vendor) { 'Global' { $script:GlobalGuid } 'Shim' { $script:ShimGuid } default { $Vendor } }
}

# Returns @{ Data = [byte[]]; Attrs = [uint32] }, or $null when the variable is absent.
function Get-FirmwareVariable {
    param([Parameter(Mandatory)] [string]$Name, [string]$Vendor = 'Global', [int]$MaxSize = 8192)
    $buf = New-Object byte[] $MaxSize
    [uint32]$attrs = 0
    $n = [Kachow.Fw]::GetFirmwareEnvironmentVariableExW($Name, (Resolve-VendorGuid $Vendor), $buf, $MaxSize, [ref]$attrs)
    if ($n -le 0) { return $null }
    @{ Data = [byte[]]$buf[0..([int]$n - 1)]; Attrs = $attrs }
}

# An empty -Value deletes the variable; deleting an absent one (error 203) is not an error.
function Set-FirmwareVariable {
    param([Parameter(Mandatory)] [string]$Name, [string]$Vendor = 'Global',
          [AllowNull()] [byte[]]$Value, [uint32]$Attrs = 7)
    $size = if ($Value) { $Value.Length } else { 0 }
    if (-not [Kachow.Fw]::SetFirmwareEnvironmentVariableExW($Name, (Resolve-VendorGuid $Vendor), $Value, [uint32]$size, $Attrs)) {
        $err = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
        if ($size -eq 0 -and $err -eq 203) { return }
        throw "Writing $Name failed (error $err)"
    }
}

# EFI_LOAD_OPTION: Attributes(4) FilePathListLength(2) Description(UCS-2, NUL) FilePathList OptionalData
function ConvertFrom-LoadOption {
    param([Parameter(Mandatory)] [byte[]]$Data)
    $pathLen = [BitConverter]::ToUInt16($Data, 4)
    $p = 6
    $desc = New-Object Text.StringBuilder
    while ($true) {
        $c = [BitConverter]::ToUInt16($Data, $p); $p += 2
        if ($c -eq 0) { break }
        [void]$desc.Append([char]$c)
    }
    $end = $p + $pathLen
    [pscustomobject]@{
        Description     = $desc.ToString()
        PathEnd         = $end
        OptionalDataLen = $Data.Length - $end
    }
}

# The first BootOrder entry described as -Description: @{ Name; Number; Var; Opt; Order }, or
# $null; -All returns every such entry in boot order.
function Find-BootEntry {
    param([Parameter(Mandatory)] [string]$Description, [switch]$All)
    $order = Get-FirmwareVariable -Name 'BootOrder'
    if (-not $order) { throw 'BootOrder not readable' }
    $found = @()
    for ($i = 0; $i -lt $order.Data.Length; $i += 2) {
        $number = [BitConverter]::ToUInt16($order.Data, $i)
        $name = 'Boot{0:X4}' -f $number
        $v = Get-FirmwareVariable -Name $name
        if (-not $v) { continue }
        $opt = ConvertFrom-LoadOption $v.Data
        if ($opt.Description -ne $Description) { continue }
        $e = @{ Name = $name; Number = $number; Var = $v; Opt = $opt; Order = $order }
        if (-not $All) { return $e }
        $found += $e
    }
    if ($All) { return , $found }
    $null
}

# Leaves exactly one -Description entry, with no optional data and no BCD object. Stripping
# alone is not enough: while the BCD object -BcdId exists, the next bcdedit firmware sync
# writes it back as a new Boot#### carrying the blob again (seen 2026-10-28). Returns it.
function Repair-BootEntry {
    param([Parameter(Mandatory)] [string]$Description, [string]$BcdId)
    $all = Find-BootEntry -Description $Description -All
    if (-not $all.Count) { throw "No boot entry named '$Description' in BootOrder" }
    if (-not @($all | Where-Object { $_.Opt.OptionalDataLen -eq 0 }).Count) { $null = Clear-BootEntryOptionalData -Entry $all[0] }
    if ($BcdId) {
        # the stripped entry no longer carries this GUID, so bcdedit removes only the BCD object
        # and any entry it re-created with the blob
        & bcdedit /delete $BcdId /f | Out-Null
        if ($LASTEXITCODE) { Write-Warning "bcdedit /delete $BcdId failed (may already be removed)" }
    }
    do {  # re-read after each removal: Remove-BootEntry rewrites BootOrder
        $dups = @((Find-BootEntry -Description $Description -All) | Where-Object { $_.Opt.OptionalDataLen })
        if ($dups.Count) { Remove-BootEntry -Entry $dups[0] }
    } while ($dups.Count)
    $left = Find-BootEntry -Description $Description -All
    if ($left.Count -ne 1) { throw "Expected one '$Description' entry, found $($left.Count)" }
    $left[0]
}

# Rewrites the entry without its optional data (bcdedit's BCD blob, which shim reads as a
# file name); returns how many bytes were removed (0: nothing to strip).
function Clear-BootEntryOptionalData {
    param([Parameter(Mandatory)] [hashtable]$Entry)
    $len = $Entry.Opt.OptionalDataLen
    if ($len -eq 0) { return 0 }
    Set-FirmwareVariable -Name $Entry.Name -Value ([byte[]]$Entry.Var.Data[0..($Entry.Opt.PathEnd - 1)]) -Attrs $Entry.Var.Attrs
    $after = Get-FirmwareVariable -Name $Entry.Name
    if (-not $after -or $after.Data.Length -ne $Entry.Opt.PathEnd) { throw "$($Entry.Name) was not rewritten as expected" }
    $len
}

# Takes the entry out of BootOrder, then deletes its Boot#### variable.
function Remove-BootEntry {
    param([Parameter(Mandatory)] [hashtable]$Entry)
    $keep = New-Object 'System.Collections.Generic.List[byte]'
    for ($i = 0; $i -lt $Entry.Order.Data.Length; $i += 2) {
        if ([BitConverter]::ToUInt16($Entry.Order.Data, $i) -ne $Entry.Number) { $keep.AddRange([byte[]]$Entry.Order.Data[$i..($i + 1)]) }
    }
    if ($keep.Count -eq 0) { throw "$($Entry.Name) is the only BootOrder entry; refusing to leave the firmware without one" }
    Set-FirmwareVariable -Name 'BootOrder' -Value $keep.ToArray() -Attrs $Entry.Order.Attrs
    Set-FirmwareVariable -Name $Entry.Name -Value $null -Attrs $Entry.Var.Attrs
}

# BootOrder as boot numbers ([uint16[]]), and back.
function ConvertFrom-BootOrder([byte[]]$Data) {
    $n = New-Object 'System.Collections.Generic.List[uint16]'
    for ($i = 0; $i + 1 -lt $Data.Length; $i += 2) { $n.Add([BitConverter]::ToUInt16($Data, $i)) }
    , $n.ToArray()
}
function ConvertTo-BootOrder([uint16[]]$Numbers) {
    $b = New-Object 'System.Collections.Generic.List[byte]'
    foreach ($x in $Numbers) { $b.AddRange([BitConverter]::GetBytes([uint16]$x)) }
    , $b.ToArray()
}

# $Order with $Number moved to position $Index (clamped), every other entry kept in order.
function Move-BootNumber {
    param([Parameter(Mandatory)] [uint16[]]$Order, [Parameter(Mandatory)] [uint16]$Number, [int]$Index = 0)
    $rest = New-Object 'System.Collections.Generic.List[uint16]'
    foreach ($x in $Order) { if ($x -ne $Number) { $rest.Add($x) } }
    $Index = [math]::Max(0, [math]::Min($Index, $rest.Count))
    $rest.Insert($Index, $Number)
    , $rest.ToArray()
}

# Puts Boot$Number first (-First) or straight after Windows Boot Manager (-AfterWindows), and
# verifies the write. Windows Boot Manager absent: -AfterWindows puts it last.
function Set-BootEntryPosition {
    param([Parameter(Mandatory)] [uint16]$Number, [switch]$First, [switch]$AfterWindows)
    $order = Get-FirmwareVariable -Name 'BootOrder'
    if (-not $order) { throw 'BootOrder not readable' }
    $numbers = ConvertFrom-BootOrder $order.Data
    $index = 0
    if ($AfterWindows) {
        $win = Find-BootEntry -Description 'Windows Boot Manager'
        $rest = @($numbers | Where-Object { $_ -ne $Number })
        $index = if ($win) { [array]::IndexOf($rest, [uint16]$win.Number) + 1 } else { $rest.Count }
    }
    $new = Move-BootNumber -Order $numbers -Number $Number -Index $index
    $bytes = ConvertTo-BootOrder $new
    Set-FirmwareVariable -Name 'BootOrder' -Value $bytes -Attrs $order.Attrs
    $after = (Get-FirmwareVariable -Name 'BootOrder').Data
    if ([BitConverter]::ToString($after) -ne [BitConverter]::ToString($bytes)) { throw 'BootOrder was not written as expected' }
    , $new
}

# One boot of Boot$Number; the firmware deletes BootNext when it uses it.
function Set-BootNext([Parameter(Mandatory)] [uint16]$Number) {
    Set-FirmwareVariable -Name 'BootNext' -Value ([BitConverter]::GetBytes($Number)) -Attrs 7
}
function Clear-BootNext { Set-FirmwareVariable -Name 'BootNext' -Value $null -Attrs 7 }

# The Boot#### number this boot started from, or $null.
function Get-BootCurrent {
    $v = Get-FirmwareVariable -Name 'BootCurrent'
    if ($v) { [BitConverter]::ToUInt16($v.Data, 0) } else { $null }
}

Export-ModuleMember -Function Enable-SystemEnvironmentPrivilege, Get-FirmwareVariable, Set-FirmwareVariable, ConvertFrom-LoadOption,
    Find-BootEntry, Clear-BootEntryOptionalData, Remove-BootEntry, Repair-BootEntry,
    ConvertFrom-BootOrder, ConvertTo-BootOrder, Move-BootNumber, Set-BootEntryPosition, Set-BootNext, Clear-BootNext,
    Get-BootCurrent
