<#
@module Machine
@description The Windows side of an install: Fast Startup, BitLocker, the hardware
preflight, the RTX's power state, a snapshot of the boot configuration before anything
changes, the logon task that carries the install across boots and then guards it, and the
keeper task that keeps the RTX powered in hybrid mode.
@output Get-FastStartup, Set-FastStartup, Suspend-BitLockerForBoots, Get-BitLockerRecovery,
        Test-HybridGraphics, Get-UnlockGpu, ConvertFrom-PowerData, Get-RtxPowerState,
        Save-MachineSnapshot, Register-LogonTask, Unregister-LogonTask, Get-LogonTask,
        Register-KeeperTask, Unregister-KeeperTask, Get-KeeperTask
@dependencies Project.psm1, FirmwareVars.psm1, Runtime.psm1; ScheduledTasks and BitLocker
        modules (Windows); everything but the preflight needs an elevated session
#>
Set-StrictMode -Version 3
Import-Module (Join-Path $PSScriptRoot 'Project.psm1')
Import-Module (Join-Path $PSScriptRoot 'FirmwareVars.psm1')
Import-Module (Join-Path $PSScriptRoot 'Runtime.psm1')

$script:PowerKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power'
$script:TaskName = 'RTX40 Ka-chow!'
$script:KeeperName = 'RTX40 Ka-chow! keeper'

# HiberbootEnabled (1 = Fast Startup on), or $null when the value is not set.
function Get-FastStartup {
    try { (Get-ItemProperty $script:PowerKey -Name HiberbootEnabled -ErrorAction Stop).HiberbootEnabled } catch { $null }
}
function Set-FastStartup([Parameter(Mandatory)] [int]$Value) {
    Set-ItemProperty -Path $script:PowerKey -Name HiberbootEnabled -Value $Value -Type DWord
}

# Suspends BitLocker on the system drive for -Boots restarts; $false when it is off or absent.
function Suspend-BitLockerForBoots([int]$Boots = 2) {
    try {
        $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop
        if ($bl.ProtectionStatus -ne 'On' -and $bl.VolumeStatus -eq 'FullyDecrypted') { return $false }
        Suspend-BitLocker -MountPoint $env:SystemDrive -RebootCount $Boots -ErrorAction Stop | Out-Null
        $true
    } catch { $false }
}

# The system drive's recovery passwords as @{ Id; Password }; empty when it has none.
function Get-BitLockerRecovery {
    try { $bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop } catch { return @() }
    @($bl.KeyProtector | Where-Object { $_.KeyProtectorType -eq 'RecoveryPassword' } |
        ForEach-Object { @{ Id = $_.KeyProtectorId; Password = $_.RecoveryPassword } })
}

# The RTX 4060 Laptop GPU (10de:28a0) display controllers.
function Get-UnlockGpu {
    @(Get-CimInstance Win32_VideoController | Where-Object { $_.PNPDeviceID -like 'PCI\VEN_10DE&DEV_28A0*' })
}

# True when another display adapter is active next to the RTX: hybrid (Optimus) mode, where
# the driver powers an idle RTX off and that resets the unlock unless the keeper holds it
# (D-20261029-002).
function Test-HybridGraphics {
    $other = @(Get-CimInstance Win32_VideoController | Where-Object {
        $_.PNPDeviceID -like 'PCI\*' -and $_.PNPDeviceID -notlike 'PCI\VEN_10DE*' -and $_.Status -eq 'OK' })
    $other.Count -gt 0
}

# CM_POWER_DATA bytes (DEVPKEY_Device_PowerData) -> 'D0'..'D3' from PD_MostRecentPowerState.
function ConvertFrom-PowerData([byte[]]$Data) {
    if ($null -eq $Data -or $Data.Length -lt 8) { return 'unknown' }
    $raw = [BitConverter]::ToInt32($Data, 4)
    if ($raw -ge 1 -and $raw -le 4) { return "D$($raw - 1)" }
    'unknown'
}

# The RTX's device power state now: D0 powered, D3 powered off; 'absent' without the device.
function Get-RtxPowerState {
    $devs = @(Get-PnpDevice -Class Display -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -like 'PCI\VEN_10DE&DEV_28A0*' })
    if (-not $devs.Count) { return 'absent' }
    $dev = $devs[0]
    try { ConvertFrom-PowerData ([byte[]](Get-PnpDeviceProperty -InstanceId $dev.InstanceId -KeyName DEVPKEY_Device_PowerData -ErrorAction Stop).Data) }
    catch { 'unknown' }
}

# Writes local\backups\pre-install-<time>.json: BootOrder, BootNext, every boot entry's
# name and description, Fast Startup and BitLocker state. Returns the path.
function Save-MachineSnapshot {
    Enable-SystemEnvironmentPrivilege
    $order = Get-FirmwareVariable -Name 'BootOrder'
    $next = Get-FirmwareVariable -Name 'BootNext'
    $entries = @()
    if ($order) {
        foreach ($n in ConvertFrom-BootOrder $order.Data) {
            $name = 'Boot{0:X4}' -f $n
            $v = Get-FirmwareVariable -Name $name
            $entries += @{ name = $name; description = $(if ($v) { (ConvertFrom-LoadOption $v.Data).Description } else { $null }) }
        }
    }
    $bl = $null
    try { $bl = (Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction Stop).ProtectionStatus.ToString() } catch { }
    $dir = Get-LocalPath 'backups'
    New-Item -ItemType Directory -Force $dir | Out-Null
    $path = Join-Path $dir ('pre-install-{0}.json' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    @{
        taken = (Get-Date -Format 'o')
        bootOrder = $(if ($order) { [BitConverter]::ToString($order.Data) } else { $null })
        bootNext = $(if ($next) { [BitConverter]::ToString($next.Data) } else { $null })
        entries = $entries
        fastStartup = Get-FastStartup
        bitLocker = $bl
    } | ConvertTo-Json -Depth 4 | Set-Content $path -Encoding utf8
    $path
}

# Runs `bin\kachow.ps1 logon` at this user's logon, elevated: in a window while an install
# is in progress (-Visible), hidden once it only guards the installed state. Only from the
# protected copy: an elevated task must not run code an ordinary account can change.
function Register-LogonTask([switch]$Visible) {
    Assert-InRuntime
    $script = Join-Path (Get-ProjectRoot) 'bin\kachow.ps1'
    $style = if ($Visible) { 'Normal' } else { 'Hidden' }
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle $style -File `"$script`" logon"
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory (Get-ProjectRoot)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
    $null = Register-ScheduledTask -TaskName $script:TaskName -Action $action -Trigger $trigger -Principal $principal `
        -Settings $settings -Description 'Carries the RTX40 Ka-chow! install across boots, then keeps its boot entry first.' -Force
}

function Unregister-LogonTask {
    if (Get-LogonTask) { Unregister-ScheduledTask -TaskName $script:TaskName -Confirm:$false }
}

function Get-LogonTask { Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue }

# Runs bin\keeper.ps1 as SYSTEM from startup, before logon, and starts it now: it holds the
# RTX so the driver never powers it off (hybrid mode, D-20261029-002). No time limit; the
# task restarts it if it stops. Script and Python both come from the protected copy. A keeper
# already running is stopped first (a running task ignores a second start); in hybrid mode
# that ends this session's hold, and the unlock returns at the next power-on.
function Register-KeeperTask {
    Assert-InRuntime
    $python = Join-Path (Get-ProjectRoot) 'python\python.exe'
    if (-not (Test-Path $python)) { throw "No Python in the protected copy ($python); run kachow.ps1 install." }
    Unregister-KeeperTask
    $script = Join-Path (Get-ProjectRoot) 'bin\keeper.ps1'
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Python `"$python`""
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg -WorkingDirectory (Get-ProjectRoot)
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $null = Register-ScheduledTask -TaskName $script:KeeperName -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) `
        -Principal $principal -Settings $settings -Description 'Keeps the RTX powered so the RTX40 Ka-chow! unlock lasts in hybrid mode.' -Force
    Start-ScheduledTask -TaskName $script:KeeperName
}

function Unregister-KeeperTask {
    if (Get-KeeperTask) {
        Stop-ScheduledTask -TaskName $script:KeeperName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $script:KeeperName -Confirm:$false
    }
    # ending the task need not end the Python it started
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*kachow.py*keep*--log*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Get-KeeperTask { Get-ScheduledTask -TaskName $script:KeeperName -ErrorAction SilentlyContinue }

Export-ModuleMember -Function Get-FastStartup, Set-FastStartup, Suspend-BitLockerForBoots, Get-BitLockerRecovery,
    Test-HybridGraphics, Get-UnlockGpu, ConvertFrom-PowerData, Get-RtxPowerState, Save-MachineSnapshot,
    Register-LogonTask, Unregister-LogonTask, Get-LogonTask, Register-KeeperTask, Unregister-KeeperTask, Get-KeeperTask
