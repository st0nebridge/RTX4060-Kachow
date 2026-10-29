<#
@module Install
@description The boot chain's pieces on this machine: the ESP files, the firmware boot
entry, the MOK enrollment request and its state, and the boot logs. Each function does one
verified step; bin/kachow.ps1 decides the order.
@output Get-UnlockerImage, Install-EspFiles, Set-EspUnlocker, Get-EspUnlockerVariant,
        Remove-EspFiles, New-ShimEntry, Get-ShimEntry, Remove-ShimEntries,
        Request-MokEnrollment, Clear-MokRequest, Test-MokPending, Test-MokEnrolled, Get-NewRunLog
@dependencies Project.psm1, Signing.psm1, Banner.psm1, FirmwareVars.psm1; bcdedit.exe;
        the ESP functions need an elevated session and the ESP mounted (Esp.psm1)
#>
Set-StrictMode -Version 3
Import-Module (Join-Path $PSScriptRoot 'Project.psm1')
Import-Module (Join-Path $PSScriptRoot 'Signing.psm1')
Import-Module (Join-Path $PSScriptRoot 'Banner.psm1')
Import-Module (Join-Path $PSScriptRoot 'FirmwareVars.psm1')

$script:EntryName = 'Tensor Unlock (shim)'
$script:EfiDir = 'EFI\tensor-unlock'
$script:AssetDir = 'GPU4090-ASSETS'
$script:LogDir = 'GPU4090-UNLOCK'
$script:Assets = @('booter_load_ad102.bin', 'v67-ad102-610.43.03-four-plm.bin',
                   'gsp_ga10x.bin', 'gsp_boot_ad102.bin', 'gsp_boot_desc_ad102.bin')
$script:Variants = @('auto', 'manual', 'dryrun', 'reltest')
$script:MokAttrs = 7  # NON_VOLATILE | BOOTSERVICE_ACCESS | RUNTIME_ACCESS, as mokutil writes them

# The signed image for -Variant, after its MOK signature and .sbat are checked: shim stops
# with "Security Violation" on anything else (CU-20261028-002).
function Get-UnlockerImage([Parameter(Mandatory)] [string]$Variant) {
    if ($script:Variants -notcontains $Variant) { throw "Unknown variant $Variant" }
    $path = Join-Path (Get-LocalPath 'build\signed') "$Variant-grubx64.efi"
    if (-not (Test-Path $path)) { throw "Missing $path - run bin\build.ps1 first." }
    Assert-MokSigned $path
    $path
}

function Copy-Verified([string]$From, [string]$To) {
    Copy-Item $From $To -Force
    if ((Get-FileHash $From).Hash -ne (Get-FileHash $To).Hash) { throw "Copy verification failed for $To" }
}

# Shim, MokManager, the certificate, the -Variant unlocker, the NVIDIA firmware and the
# banner, each hash-checked after copying.
function Install-EspFiles {
    param([Parameter(Mandatory)] [string]$Esp, [Parameter(Mandatory)] [string]$Variant)
    $image = Get-UnlockerImage $Variant
    $efi = Join-Path $Esp $script:EfiDir
    $assets = Join-Path $Esp $script:AssetDir
    if (-not (Test-Path $efi)) {
        $free = [math]::Floor(([IO.DriveInfo]::new($Esp)).AvailableFreeSpace / 1MB)
        if ($free -lt 118) { throw "ESP has $free MB free; need 118 MB (86 MB plus headroom for Windows updates)." }
    }
    New-Item -ItemType Directory -Force $efi, $assets | Out-Null
    Copy-Verified (Get-LocalPath 'efi\shimx64.efi') (Join-Path $efi 'shimx64.efi')
    Copy-Verified $image (Join-Path $efi 'grubx64.efi')    # shim loads grubx64.efi
    Copy-Verified (Get-LocalPath 'efi\mmx64.efi') (Join-Path $efi 'mmx64.efi')
    Copy-Verified (Get-LocalPath 'keys\MOK.cer') (Join-Path $efi 'MOK.cer')
    foreach ($a in $script:Assets) { Copy-Verified (Get-LocalPath "assets\$a") (Join-Path $assets $a) }
    $null = Install-EspBanner -Esp $Esp
}

# Swaps the unlocker image on an installed ESP.
function Set-EspUnlocker {
    param([Parameter(Mandatory)] [string]$Esp, [Parameter(Mandatory)] [string]$Variant)
    $image = Get-UnlockerImage $Variant
    $dst = Join-Path $Esp "$script:EfiDir\grubx64.efi"
    if (-not (Test-Path (Split-Path $dst))) { throw "No \$script:EfiDir\ on the ESP - install first." }
    Copy-Verified $image $dst
    $null = Install-EspBanner -Esp $Esp
}

# Which signed build the ESP's grubx64.efi is ('auto', ...), 'unknown', or $null when absent.
function Get-EspUnlockerVariant([Parameter(Mandatory)] [string]$Esp) {
    $dst = Join-Path $Esp "$script:EfiDir\grubx64.efi"
    if (-not (Test-Path $dst)) { return $null }
    $hash = (Get-FileHash $dst).Hash
    foreach ($v in $script:Variants) {
        $p = Join-Path (Get-LocalPath 'build\signed') "$v-grubx64.efi"
        if ((Test-Path $p) -and (Get-FileHash $p).Hash -eq $hash) { return $v }
    }
    'unknown'
}

# Removes the boot chain's directories, after copying the boot logs to
# local\logs\esp-<time>\; returns the paths removed.
function Remove-EspFiles([Parameter(Mandatory)] [string]$Esp) {
    $logs = Join-Path $Esp $script:LogDir
    if (Test-Path $logs) {
        $keep = Get-LocalPath ('logs\esp-{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
        New-Item -ItemType Directory -Force $keep | Out-Null
        Copy-Item (Join-Path $logs '*') $keep -Force
    }
    foreach ($d in $script:EfiDir, $script:AssetDir, $script:LogDir) {
        $p = Join-Path $Esp $d
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -Confirm:$false; $p }
    }
}

function Get-ShimEntry { Find-BootEntry -Description $script:EntryName }

# Creates the firmware entry for shim on -Esp through bcdedit, then detaches it from the BCD
# store (CU-20261028-009): no optional data, no BCD object. Returns the entry.
function New-ShimEntry([Parameter(Mandatory)] [string]$Esp) {
    $out = & bcdedit /copy '{bootmgr}' /d $script:EntryName
    $id = [regex]::Match(($out -join ' '), '\{[0-9a-fA-F-]{36}\}').Value
    if (-not $id) { throw "bcdedit /copy did not return an entry ID: $out" }
    & bcdedit /set $id path "\$script:EfiDir\shimx64.efi" | Out-Null
    if ($LASTEXITCODE) { throw 'bcdedit set path failed' }
    & bcdedit /set $id device "partition=$($Esp.TrimEnd('\'))" | Out-Null
    if ($LASTEXITCODE) { throw 'bcdedit set device failed' }
    & bcdedit /set '{fwbootmgr}' displayorder $id /addlast | Out-Null
    if ($LASTEXITCODE) { throw 'bcdedit displayorder failed' }
    Enable-SystemEnvironmentPrivilege
    Repair-BootEntry -Description $script:EntryName -BcdId $id
}

# Removes every firmware entry named like ours (and a BCD object an old install recorded);
# returns the Boot#### names removed.
function Remove-ShimEntries([string]$BcdId) {
    if ($BcdId) {
        & bcdedit /delete $BcdId /f | Out-Null
        if ($LASTEXITCODE) { Write-Warning "bcdedit /delete $BcdId failed (may already be removed)" }
    }
    Enable-SystemEnvironmentPrivilege
    do {  # re-read after each removal: Remove-BootEntry rewrites BootOrder
        $e = Get-ShimEntry
        if ($e) { Remove-BootEntry -Entry $e; $e.Name }
    } while ($e)
}

# Stages shim's MokNew/MokAuth (the equivalent of `mokutil --import MOK.cer`): on the next
# boot through shim, MokManager opens "Enroll MOK" and asks for -Password.
function Request-MokEnrollment([Parameter(Mandatory)] [string]$Password) {
    Enable-SystemEnvironmentPrivilege
    $dir = Get-LocalPath 'mok'
    $null = Invoke-Kachow -Arguments @('mok-payload', (Get-LocalPath 'keys\MOK.cer'), $dir, '--password', $Password)
    $new = [IO.File]::ReadAllBytes((Join-Path $dir 'MokNew.bin'))
    $auth = [IO.File]::ReadAllBytes((Join-Path $dir 'MokAuth.bin'))
    Set-FirmwareVariable -Name 'MokNew' -Vendor Shim -Value $new -Attrs $script:MokAttrs
    Set-FirmwareVariable -Name 'MokAuth' -Vendor Shim -Value $auth -Attrs $script:MokAttrs
    $staged = Get-FirmwareVariable -Name 'MokNew' -Vendor Shim
    if (-not $staged -or $staged.Data.Length -ne $new.Length) { throw 'MokNew was not staged as expected' }
}

# Withdraws a pending request (the equivalent of `mokutil --revoke-import`).
function Clear-MokRequest {
    Enable-SystemEnvironmentPrivilege
    Set-FirmwareVariable -Name 'MokNew' -Vendor Shim -Value $null -Attrs $script:MokAttrs
    Set-FirmwareVariable -Name 'MokAuth' -Vendor Shim -Value $null -Attrs $script:MokAttrs
}

function Test-MokPending {
    Enable-SystemEnvironmentPrivilege
    $null -ne (Get-FirmwareVariable -Name 'MokNew' -Vendor Shim)
}

# Whether shim trusts local\keys\MOK.cer. Shim publishes its MokList as MokListRT only on a
# boot it started, so a sighting is remembered in local\mok-enrolled.json (by thumbprint).
function Test-MokEnrolled {
    Enable-SystemEnvironmentPrivilege
    $cer = [IO.File]::ReadAllBytes((Get-LocalPath 'keys\MOK.cer'))
    $thumb = (Get-MokCertificate).Thumbprint
    $marker = Get-LocalPath 'mok-enrolled.json'
    $list = Get-FirmwareVariable -Name 'MokListRT' -Vendor Shim -MaxSize 65536
    if ($list -and [BitConverter]::ToString($list.Data).Contains([BitConverter]::ToString($cer))) {
        @{ thumbprint = $thumb; seen = (Get-Date -Format 'o') } | ConvertTo-Json | Set-Content $marker -Encoding utf8
        return $true
    }
    (Test-Path $marker) -and (Get-Content $marker -Raw | ConvertFrom-Json).thumbprint -eq $thumb
}

# The newest RUNnnnn.TXT numbered above -After, copied to -Into (local\logs): @{ Number;
# Path }, or $null when there is none.
function Get-NewRunLog {
    param([Parameter(Mandatory)] [string]$Esp, [int]$After = 0, [string]$Into = (Get-LocalPath 'logs'))
    $dir = Join-Path $Esp $script:LogDir
    if (-not (Test-Path $dir)) { return $null }
    $best = $null
    foreach ($f in Get-ChildItem $dir -Filter 'RUN*.TXT') {
        $m = [regex]::Match($f.Name, '^RUN(\d+)\.TXT$')
        if ($m.Success -and [int]$m.Groups[1].Value -gt $After -and
            (-not $best -or [int]$m.Groups[1].Value -gt $best.Number)) {
            $best = @{ Number = [int]$m.Groups[1].Value; File = $f }
        }
    }
    if (-not $best) { return $null }
    New-Item -ItemType Directory -Force $Into | Out-Null
    $copy = Join-Path $Into $best.File.Name
    Copy-Item $best.File.FullName $copy -Force
    @{ Number = $best.Number; Path = $copy }
}

Export-ModuleMember -Function Get-UnlockerImage, Install-EspFiles, Set-EspUnlocker, Get-EspUnlockerVariant,
    Remove-EspFiles, New-ShimEntry, Get-ShimEntry, Remove-ShimEntries,
    Request-MokEnrollment, Clear-MokRequest, Test-MokPending, Test-MokEnrolled, Get-NewRunLog
