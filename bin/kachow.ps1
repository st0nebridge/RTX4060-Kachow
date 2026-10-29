#Requires -Version 5.1
<#
.SYNOPSIS
  RTX4060 Ka-chow! in one command: install, uninstall, status, recover.
.DESCRIPTION
  install    Checks the machine, saves a snapshot of its boot configuration, puts the boot
             chain on the ESP and asks the firmware for one trial boot of the dry-run build
             (BootNext). Windows Boot Manager stays first in the boot order until a boot has
             unlocked, so a failed boot is cured by powering off and on. A logon task brings
             this script back after each power-on: key enrollment if needed, the trial, the
             first unlock, and only then is the boot entry put first. From then on the task
             only checks, at each logon, that the entry is still there and first.
             After the first unlock a keeper task (SYSTEM, at startup) holds the RTX so the
             driver never powers it off: in hybrid mode that power-off resets the unlock.
  uninstall  Removes the logon and keeper tasks, the boot entry and the ESP files (boot logs are kept
             in local\logs), and restores Fast Startup if an earlier install turned it off.
             The enrolled key stays.
  status     What is installed and what the last boot did.
  recover    Windows Boot Manager first again, no one-time boot, logon task off; the files
             stay. install starts again from the trial.
  Asks before changing anything unless -Yes. Elevates itself.
.EXAMPLE
  .\bin\kachow.ps1 install
  .\bin\kachow.ps1 status
  .\bin\kachow.ps1 uninstall
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)] [ValidateSet('install', 'uninstall', 'status', 'recover', 'logon')]
    [string]$Command = 'status',
    [switch]$Yes,
    [string]$Password = 'tensor',
    [switch]$Elevated
)
$ErrorActionPreference = 'Stop'
# Elevated at every logon: autoload modules only from the admin-only folders, never from the
# user's Documents\WindowsPowerShell\Modules, where a planted Storage or ScheduledTasks would run.
$env:PSModulePath = (Join-Path $env:SystemRoot 'system32\WindowsPowerShell\v1.0\Modules') + ';' + (Join-Path $env:ProgramFiles 'WindowsPowerShell\Modules')

$me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", $Command, '-Elevated', '-Password', $Password)
    if ($Yes) { $argList += '-Yes' }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argList -Wait
    exit
}

foreach ($m in 'Project', 'Runtime', 'Signing', 'Esp', 'FirmwareVars', 'Install', 'Machine') {
    Import-Module (Join-Path $PSScriptRoot "..\src\windows\$m.psm1") -Force
}

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }

function Confirm-Step([string]$Question) {
    if ($Yes) { return $true }
    (Read-Host "$Question [y/N]") -match '^\s*[yY]'
}

function Get-Record {
    $r = Read-InstallRecord
    if (-not $r) { return $null }
    $h = @{}
    $r.PSObject.Properties | ForEach-Object { $h[$_.Name] = $_.Value }
    $h
}

function Save-Record([hashtable]$Rec) {
    $Rec.updated = Get-Date -Format 'o'
    $null = Write-InstallRecord $Rec
}

# The scriptblock's last output: Invoke-WithEsp also passes on whatever mountvol prints.
function Use-Esp([scriptblock]$Action) { @(Invoke-WithEsp $Action) | Select-Object -Last 1 }

function Get-RunLogFacts([string]$Path) {
    # runlog exits 1 for a boot that did not unlock; the facts are still wanted
    (Invoke-Kachow -Arguments @('runlog', $Path, '--json') -Capture -AllowFailure) -join "`n" | ConvertFrom-Json
}

# This boot's line from bin\keeper.ps1 in keeper.log, as @{ Line; Uptime; Rtx }, or $null.
function Get-KeeperStart {
    $path = Get-LocalPath 'logs\keeper.log'
    if (-not (Test-Path $path)) { return $null }
    $boot = '{0:o}' -f (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
    $line = @(Get-Content $path | Where-Object { $_ -like "* start boot=$boot *" }) | Select-Object -Last 1
    if (-not $line -or $line -notmatch 'uptime=(\d+)s RTX=(\S+)') { return $null }
    @{ Line = $line; Uptime = [int]$Matches[1]; Rtx = $Matches[2] }
}

function Invoke-Shutdown {
    Say 'Shut down (not Restart), then power on: the unlocker needs the GPU fresh from power-on.' Yellow
    if ($Yes -or (Read-Host 'Shut down now? [Y/n]') -notmatch '^\s*[nN]') { & shutdown.exe /s /t 0 }
    else { Say 'Shut down when you are ready; this carries on at the next logon.' }
}

function Show-MokSteps {
    Say "At power-on a blue MokManager screen appears. Press a key within 10 s, then:" Yellow
    Say "  Enroll MOK -> Continue -> Yes -> type the password '$Password' -> Reboot" Yellow
    Say 'It restarts into Windows. Log in and this window comes back by itself.' Yellow
}

function Assert-Preflight {
    try { $sb = Confirm-SecureBootUEFI } catch { throw 'This PC is not booted in UEFI mode.' }
    if (-not $sb) { Say 'Secure Boot is off. The chain works either way; it was built for Secure Boot on.' Yellow }
    $gpus = Get-UnlockGpu
    if ($gpus.Count -ne 1) { throw "Expected exactly one RTX 4060 Laptop GPU (10de:28a0), found $($gpus.Count)." }
    Say "GPU: $($gpus[0].Name)"
    if (Test-HybridGraphics) {
        Say 'Hybrid (Optimus) mode: the driver powers an idle RTX off, and that resets the unlock. After the' Yellow
        Say 'first unlock the keeper task holds the RTX (about 2 W) so the unlock lasts the whole session.' Yellow
    }
    $null = Invoke-Kachow -Arguments @('verify')    # shim, MokManager, firmware: pinned hashes
    foreach ($v in 'dryrun', 'auto') {
        if (-not (Test-Path (Join-Path (Get-LocalPath 'build\signed') "$v-grubx64.efi"))) {
            throw "Signed $v image missing from $(Get-LocalPath 'build\signed'); run install from the repository, which builds it."
        }
    }
    foreach ($v in 'dryrun', 'auto') { $null = Get-UnlockerImage $v }
}

# An install made before this script (no phase in its record) whose last boot unlocked.
function Invoke-Adopt([hashtable]$Rec) {
    Enable-SystemEnvironmentPrivilege
    $entry = Get-ShimEntry
    if (-not $entry) { return $false }
    $log = Use-Esp { param($esp) Get-NewRunLog -Esp $esp -After 0 }
    if (-not $log) { return $false }
    $facts = Get-RunLogFacts $log.Path
    if ($facts.status -ne 'unlocked' -or -not $facts.via_shim) { return $false }
    Say "Found an install from before kachow.ps1: $($entry.Name), last boot RUN$('{0:D4}' -f $log.Number) unlocked."
    Say 'Adopting it detaches the entry from bcdedit if needed, keeps it first and adds the logon and keeper tasks.'
    if (-not (Confirm-Step 'Adopt it?')) { Say 'Nothing was changed.'; return $true }
    # what fix-bootentry.ps1 did: no optional data, no BCD object (CU-20261028-009)
    $entry = Repair-BootEntry -Description $entry.Opt.Description -BcdId $Rec['entryId']
    $Rec.entryId = $null
    $null = Set-BootEntryPosition -Number $entry.Number -First
    $Rec.phase = 'installed'; $Rec.attempts = 0; $Rec.lastRun = $log.Number
    $Rec.firmwareEntry = $entry.Name; $Rec.entryNumber = [int]$entry.Number
    Save-Record $Rec
    Register-LogonTask
    Register-KeeperTask
    Say 'Adopted. The logon task now keeps the boot entry first; the keeper task holds the RTX.' Green
    $true
}

function Invoke-Install {
    $rec = Get-Record
    if ($rec -and $rec['phase'] -in 'trial', 'unlock') { Say "An install is in progress ($($rec.phase)); carrying on."; Invoke-Resume $rec; return }
    if ($rec -and $rec['phase'] -eq 'installed') {
        Register-LogonTask; Register-KeeperTask
        Say 'Already installed. The logon and keeper tasks run from the protected copy.' Green; Show-Status; return
    }
    if ($rec -and -not $rec.ContainsKey('phase') -and (Invoke-Adopt $rec)) { return }

    Assert-Preflight
    $mokKnown = Test-MokEnrolled
    Say "`nThe plan:" Cyan
    Say '  1. Save the boot configuration to local\backups (BootOrder, entries, Fast Startup, BitLocker).'
    Say '  2. Copy shim, MokManager, the dry-run unlocker, the NVIDIA firmware and the banner to the ESP.'
    Say "  3. Add the boot entry 'Tensor Unlock (shim)' after Windows Boot Manager, and ask for one boot of it."
    if (-not $mokKnown) { Say "  4. Stage the key enrollment (password '$Password')." }
    Say '  5. Suspend BitLocker for the next boots; add the logon task. Fast Startup stays as it is.'
    Say '  Then: trial boot (checks only, no GPU writes) -> first unlock boot -> boot entry first, and the'
    Say '  keeper task, which keeps the RTX powered so the unlock lasts in hybrid mode.'
    $keys = Get-BitLockerRecovery
    if ($keys.Count) {
        Say "`nBitLocker is on. Its recovery key, in case the firmware asks for it (keep a copy off this PC):" Yellow
        foreach ($k in $keys) { Say "  $($k.Id)  $($k.Password)" Yellow }
    }
    if (-not (Confirm-Step "`nInstall now?")) { Say 'Nothing was changed.'; return }

    $snapshot = Save-MachineSnapshot
    Say "Snapshot: $snapshot"
    $done = Use-Esp {
        param($esp)
        Install-EspFiles -Esp $esp -Variant dryrun
        $e = Get-ShimEntry
        if (-not $e) { $e = New-ShimEntry -Esp $esp }
        $last = Get-NewRunLog -Esp $esp -After 0
        @{ Entry = $e; LastRun = $(if ($last) { $last.Number } else { 0 }) }
    }
    $entry = $done.Entry
    Say "ESP files copied and verified; boot entry $($entry.Name)."
    Enable-SystemEnvironmentPrivilege
    $null = Set-BootEntryPosition -Number $entry.Number -AfterWindows
    Set-BootNext $entry.Number
    if (-not $mokKnown) { Request-MokEnrollment $Password }
    $null = Suspend-BitLockerForBoots 3
    $new = @{
        phase = 'trial'; attempts = 0; lastRun = $done.LastRun; firmwareEntry = $entry.Name
        entryNumber = [int]$entry.Number; entryId = $null; mode = 'dryrun'
        installed = (Get-Date -Format 'o'); snapshot = $snapshot
        espEfiDir = '\EFI\tensor-unlock'; espAssetDir = '\GPU4090-ASSETS'
    }
    # an earlier install saved the Fast Startup value it replaced; uninstall restores it
    if ($rec -and $rec.ContainsKey('fastStartup')) { $new.fastStartup = $rec.fastStartup }
    Save-Record $new
    Register-LogonTask -Visible
    Say "`nInstalled for a trial boot." Green
    if (-not $mokKnown) { Show-MokSteps }
    else { Say 'The next power-on runs the trial (checks only), then Windows. Log in and this window comes back.' }
    Invoke-Shutdown
}

function Invoke-Resume([hashtable]$Rec) {
    Enable-SystemEnvironmentPrivilege
    $number = [uint16]$Rec.entryNumber
    $viaEntry = (Get-BootCurrent) -eq $number
    $pending = Test-MokPending
    $null = Test-MokEnrolled    # remembers it when this boot went through shim
    $log = Use-Esp { param($esp) Get-NewRunLog -Esp $esp -After ([int]$Rec.lastRun) }
    $argList = @('next-step', '--phase', $Rec.phase, '--attempts', [string]$Rec.attempts)
    if ($log) { $argList += @('--log', $log.Path) }
    if ($viaEntry) { $argList += '--via-entry' }
    if ($pending) { $argList += '--mok-pending' }
    $step = (Invoke-Kachow -Arguments $argList -Capture) -join "`n" | ConvertFrom-Json
    if ($log) { $null = Invoke-Kachow -Arguments @('runlog', $log.Path) -AllowFailure }
    else { Say 'No new boot log since the last step.' }
    if ($log) { $Rec.lastRun = $log.Number }
    Say $step.message $(if ($step.action -eq 'stop') { 'Red' } else { 'Cyan' })

    switch ($step.action) {
        'retry' {
            $Rec.attempts = [int]$Rec.attempts + 1
            Set-BootNext $number
            $staged = $false
            if ($Rec.phase -eq 'trial' -and -not $pending -and -not (Test-MokEnrolled)) { Request-MokEnrollment $Password; $staged = $true }
            $null = Suspend-BitLockerForBoots 2
            Save-Record $Rec
            if ($staged) { Show-MokSteps }
            Invoke-Shutdown
        }
        'advance' {
            Use-Esp { param($esp) Set-EspUnlocker -Esp $esp -Variant auto } | Out-Null
            $Rec.phase = 'unlock'; $Rec.attempts = 0; $Rec.mode = 'auto'
            Set-BootNext $number
            $null = Suspend-BitLockerForBoots 2
            Save-Record $Rec
            Say 'Next power-on: the unlocker counts down 3 s and unlocks. (Esc there starts Windows without it.)'
            Invoke-Shutdown
        }
        'finish' {
            $null = Set-BootEntryPosition -Number $number -First
            $Rec.phase = 'installed'; $Rec.attempts = 0
            Save-Record $Rec
            Register-LogonTask
            Register-KeeperTask
            Say 'The boot entry is now first: every power-on unlocks. The logon task keeps it first.' Green
            Say 'The keeper task holds the RTX from each startup, so hybrid mode keeps the unlock too.' Green
            $bench = Get-LocalPath '.venv-bench\Scripts\python.exe'
            if (Test-Path $bench) { & (Join-Path $PSScriptRoot 'bench.ps1') }
        }
        'stop' {
            Clear-BootNext
            $null = Set-BootEntryPosition -Number $number -AfterWindows
            Unregister-LogonTask
            Unregister-KeeperTask
            $Rec.phase = 'failed'
            Save-Record $Rec
            Say 'Windows Boot Manager boots first, as before. Run install to try again, or uninstall.' Yellow
        }
    }
}

# The logon task, installed state: put things back if Windows moved them, and log it.
function Invoke-Guard([hashtable]$Rec) {
    Enable-SystemEnvironmentPrivilege
    $notes = New-Object 'System.Collections.Generic.List[string]'
    $entry = Get-ShimEntry
    if (-not $entry) {
        $entry = Use-Esp {
            param($esp)
            if (-not (Get-EspUnlockerVariant $esp)) { Install-EspFiles -Esp $esp -Variant auto }
            New-ShimEntry -Esp $esp
        }
        $notes.Add("boot entry was missing; re-created as $($entry.Name)")
        $Rec.firmwareEntry = $entry.Name; $Rec.entryNumber = [int]$entry.Number
    }
    $order = ConvertFrom-BootOrder (Get-FirmwareVariable -Name 'BootOrder').Data
    if ($order[0] -ne $entry.Number) {
        $null = Set-BootEntryPosition -Number $entry.Number -First
        $notes.Add(('Boot{0:X4} had been put first; {1} is first again' -f $order[0], $entry.Name))
    }
    $log = Use-Esp { param($esp) Get-NewRunLog -Esp $esp -After ([int]$Rec.lastRun) }
    if ($log) {
        $facts = Get-RunLogFacts $log.Path
        $notes.Add(('RUN{0:D4} status={1}' -f $log.Number, $facts.status))
        $Rec.lastRun = $log.Number
    }
    if (-not (Get-KeeperTask)) { Register-KeeperTask; $notes.Add('keeper task was missing; added again') }
    $start = Get-KeeperStart
    if ($start -and $start.Rtx -eq 'D3') { $notes.Add('the RTX was off (D3) before the keeper started: the unlock may have been reset; bench.ps1 says whether it is active') }
    Save-Record $Rec
    $line = '{0} {1}' -f (Get-Date -Format 's'), $(if ($notes.Count) { $notes -join '; ' } else { 'ok' })
    Add-Content -Path (Get-LocalPath 'logs\guard.log') -Value $line -Encoding utf8
}

function Invoke-Logon {
    $rec = Get-Record
    if ($rec -and $rec['phase'] -in 'trial', 'unlock') { Invoke-Resume $rec; $script:Pause = $true }
    elseif ($rec -and $rec['phase'] -eq 'installed') { Invoke-Guard $rec }
    else { Unregister-LogonTask }
}

function Show-Status {
    Enable-SystemEnvironmentPrivilege
    $rec = Get-Record
    $phase = if (-not $rec) { 'not installed' } elseif ($rec.ContainsKey('phase')) { $rec.phase } else { 'installed (before kachow.ps1)' }
    Say "Install:      $phase$(if ($rec -and $rec['attempts']) { " (attempt $([int]$rec.attempts + 1))" })"
    $entry = Get-ShimEntry
    if ($entry) {
        $order = ConvertFrom-BootOrder (Get-FirmwareVariable -Name 'BootOrder').Data
        $pos = [array]::IndexOf($order, [uint16]$entry.Number) + 1
        Say "Boot entry:   $($entry.Name), position $pos of $($order.Count)$(if ($pos -eq 1) { ' (first)' })"
    } else { Say 'Boot entry:   none' }
    $next = Get-FirmwareVariable -Name 'BootNext'
    if ($next) { Say ('One-time boot: Boot{0:X4}' -f [BitConverter]::ToUInt16($next.Data, 0)) }
    $current = Get-BootCurrent
    Say ('This boot:    Boot{0:X4}{1}' -f $current, $(if ($entry -and $current -eq $entry.Number) { ' (through shim)' } else { '' }))
    Say "Key:          $(if (Test-MokEnrolled) { 'enrolled' } elseif (Test-MokPending) { 'enrollment pending' } else { 'not seen enrolled' })"
    if ($entry -and $current -eq $entry.Number) {
        $sb = Get-FirmwareVariable -Name 'MokSBStateRT' -Vendor Shim
        Say "Shim checks:  $(if ($sb -and $sb.Data[0]) { 'OFF (MokSBState): shim starts images unverified' } else { 'on' })"
    }
    $esp = Use-Esp {
        param($esp)
        @{ Variant = Get-EspUnlockerVariant $esp; Log = Get-NewRunLog -Esp $esp -After 0 }
    }
    Say "ESP unlocker: $(if ($esp.Variant) { $esp.Variant } else { 'none' })"
    if ($esp.Log) { Write-Host -NoNewline ('Last boot:    RUN{0:D4} ' -f $esp.Log.Number); $null = Invoke-Kachow -Arguments @('runlog', $esp.Log.Path) -AllowFailure }
    $task = Get-LogonTask
    Say "Logon task:   $(if ($task) { $task.State } else { 'none' })"
    $hybrid = Test-HybridGraphics
    Say "GPU mode:     $(if ($hybrid) { 'hybrid (Intel GPU active): the keeper must hold the RTX' } else { 'discrete' })"
    $keeper = Get-KeeperTask
    Say "Keeper:       $(if ($keeper) { $keeper.State } elseif ($hybrid) { 'none - the unlock is lost when the RTX powers off; run install' } else { 'none' })"
    $start = Get-KeeperStart
    if ($start) { Say "Keeper start: uptime $($start.Uptime) s, RTX was $($start.Rtx)$(if ($start.Rtx -eq 'D3') { ' (off before the keeper: the unlock may have been reset; check with bench.ps1)' })" }
    Say "RTX power:    $(Get-RtxPowerState)"
    $fs = Get-FastStartup
    Say "Fast Startup: $(if ($fs -eq 0) { 'off' } elseif ($fs -eq 1) { 'on' } else { 'not set' }) (either way, Shut down, Restart or Hibernate unlocks; Sleep does not)"
    $guard = Get-LocalPath 'logs\guard.log'
    if (Test-Path $guard) { Say "Guard:        $(@(Get-Content $guard) | Select-Object -Last 1)" }
    Say 'Unlock active right now? .\bin\bench.ps1'
}

function Invoke-Recover {
    if (-not (Confirm-Step 'Put Windows Boot Manager first and stop starting the unlocker?')) { return }
    Enable-SystemEnvironmentPrivilege
    Clear-BootNext
    $entry = Get-ShimEntry
    if ($entry) { $null = Set-BootEntryPosition -Number $entry.Number -AfterWindows }
    Unregister-LogonTask
    Unregister-KeeperTask
    $rec = Get-Record
    if ($rec) { $rec.phase = 'recovered'; Save-Record $rec }
    Say 'Windows Boot Manager boots first; the unlocker no longer runs. The files stay on the ESP.' Green
    Say 'install starts again from the trial boot; uninstall removes everything.'
}

function Invoke-Uninstall {
    $rec = Get-Record
    Say 'The plan: remove the logon and keeper tasks, any one-time boot, the boot entry and the ESP files' Cyan
    Say '(\EFI\tensor-unlock, \GPU4090-ASSETS, \GPU4090-UNLOCK; the logs are copied to local\logs first),' Cyan
    if ($rec -and $null -ne $rec['fastStartup'] -and $rec.fastStartup -ne 0) { Say "restore Fast Startup (HiberbootEnabled=$($rec.fastStartup))," Cyan }
    Say 'and keep the install record in local\backups. The enrolled key stays: shim trusts only images signed with it.' Cyan
    if (-not (Confirm-Step 'Uninstall now?')) { Say 'Nothing was changed.'; return }
    Unregister-LogonTask
    Unregister-KeeperTask
    Enable-SystemEnvironmentPrivilege
    Clear-BootNext
    Clear-MokRequest
    $bcd =if ($rec) { $rec['entryId'] } else { $null }
    foreach ($name in Remove-ShimEntries -BcdId $bcd) { Say "Removed boot entry $name" }
    foreach ($p in @(Invoke-WithEsp { param($esp) Remove-EspFiles $esp })) { Say "Removed $p" }
    if ($rec -and $null -ne $rec['fastStartup'] -and $rec.fastStartup -ne 0) { Set-FastStartup $rec.fastStartup; Say 'Fast Startup restored.' }
    $path = Get-LocalPath 'install-record.json'
    if (Test-Path $path) {
        $dir = Get-LocalPath 'backups'
        New-Item -ItemType Directory -Force $dir | Out-Null
        Move-Item $path (Join-Path $dir ('install-record-{0}.json' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))) -Force
    }
    Say 'Uninstalled. Windows boots as before.' Green
}

if (-not (Test-InRuntime)) {
    # Every command runs from the protected copy in Program Files, which only Administrators
    # and SYSTEM can change (security review 2026-10-29, M-1). install refreshes it first.
    # Without a copy (an install made before it existed) the other commands run in place.
    $code = $null
    try {
        if ($Command -eq 'install') {
            Protect-SigningKey
            foreach ($v in 'dryrun', 'auto') {
                if (-not (Test-Path (Join-Path (Get-LocalPath 'build\signed') "$v-grubx64.efi"))) {
                    Say 'Signed images missing: building them.'
                    & (Join-Path $PSScriptRoot 'build.ps1')
                    break
                }
            }
            Say "Refreshing the protected copy in $(Get-RuntimeRoot) ..."
            $null = Install-Runtime
        }
        if (Test-Path (Join-Path (Get-RuntimeRoot) 'bin\kachow.ps1')) {
            $code = Invoke-RuntimeCommand -Command $Command -Yes:$Yes -Password $Password
            if ($Command -eq 'uninstall' -and -not $code) { Remove-Runtime; Say "Removed $(Get-RuntimeRoot)." Green }
        }
    } catch {
        Say "kachow $Command failed: $($_.Exception.Message)" Red
        $code = 1
    }
    if ($null -ne $code) {
        if ($Elevated) { $null = Read-Host 'Press Enter to close' }
        exit $code
    }
}

$script:Pause = $Elevated
$failed = $false
try {
    switch ($Command) {
        'install' { Invoke-Install }
        'uninstall' { Invoke-Uninstall }
        'status' { Show-Status }
        'recover' { Invoke-Recover }
        'logon' { Invoke-Logon }
    }
} catch {
    Say "kachow $Command failed: $($_.Exception.Message)" Red
    Say 'Nothing after the failed step ran. .\bin\kachow.ps1 status shows where things are; recover or uninstall undo it.' Red
    $script:Pause = $true
    $failed = $true
}
if ($script:Pause) { $null = Read-Host 'Press Enter to close' }
if ($failed) { exit 1 }
