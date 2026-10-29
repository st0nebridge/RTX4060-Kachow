"""Regression test CU-20261028-012 (one-command install, uninstall and recovery): the boot
entry is only ever tried through a one-time boot (BootNext) with Windows Boot Manager first,
and goes first only after a boot proved the unlock; a failed step puts Windows first again;
the logon task carries the install and then guards it; uninstall keeps the boot logs and
works without an install record."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
INSTALL = (REPO / 'src' / 'windows' / 'Install.psm1').read_text('utf-8')
FW = (REPO / 'src' / 'windows' / 'FirmwareVars.psm1').read_text('utf-8')


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_install_tries_the_entry_once_with_windows_first():
    b = body(SCRIPT, 'Invoke-Install')
    assert 'Set-BootEntryPosition -Number $entry.Number -AfterWindows' in b
    assert b.index('-AfterWindows') < b.index('Set-BootNext $entry.Number')
    assert 'Install-EspFiles -Esp $esp -Variant dryrun' in b and '-First' not in b
    assert b.index('Save-MachineSnapshot') < b.index('Install-EspFiles')
    assert b.index('Confirm-Step') < b.index('Save-MachineSnapshot')


def test_the_entry_goes_first_only_after_an_unlocked_boot():
    firsts = [m.start() for m in re.finditer(r'Set-BootEntryPosition[^\n]*-First', SCRIPT)]
    assert len(firsts) == 3   # finish, adopting an unlocked install, and the guard
    resume = body(SCRIPT, 'Invoke-Resume')
    finish = resume[resume.index("'finish' {"):resume.index("'stop' {")]
    assert '-First' in finish and resume.count('-First') == 1
    adopt = body(SCRIPT, 'Invoke-Adopt')
    assert adopt.index("$facts.status -ne 'unlocked'") < adopt.index('-First')
    assert body(SCRIPT, 'Invoke-Guard').count('-First') == 1


def test_a_failed_step_puts_windows_first_and_stops_the_task():
    resume = body(SCRIPT, 'Invoke-Resume')
    stop = resume[resume.index("'stop' {"):]
    assert 'Clear-BootNext' in stop and '-AfterWindows' in stop and 'Unregister-LogonTask' in stop
    recover = body(SCRIPT, 'Invoke-Recover')
    assert 'Clear-BootNext' in recover and '-AfterWindows' in recover and 'Unregister-LogonTask' in recover


def test_each_boot_step_is_decided_by_the_tested_lifecycle_module():
    resume = body(SCRIPT, 'Invoke-Resume')
    assert "@('next-step', '--phase', $Rec.phase" in resume
    for action in ("'retry'", "'advance'", "'finish'", "'stop'"):
        assert action in resume
    assert "Set-EspUnlocker -Esp $esp -Variant auto" in resume[resume.index("'advance' {"):resume.index("'finish' {")]


def test_the_logon_task_resumes_then_guards():
    logon = body(SCRIPT, 'Invoke-Logon')
    assert "'trial', 'unlock'" in logon and 'Invoke-Resume' in logon and 'Invoke-Guard' in logon
    assert 'Register-LogonTask -Visible' in body(SCRIPT, 'Invoke-Install')
    assert 'Register-LogonTask\n' in body(SCRIPT, 'Invoke-Resume')   # hidden once installed
    assert 'guard.log' in body(SCRIPT, 'Invoke-Guard')


def test_uninstall_works_without_a_record_and_keeps_the_logs():
    b = body(SCRIPT, 'Invoke-Uninstall')
    assert 'Remove-ShimEntries -BcdId $bcd' in b and 'Remove-EspFiles' in b and 'Clear-MokRequest' in b
    assert "if ($rec) { $rec['entryId'] } else { $null }" in b
    removal = body(INSTALL, 'Remove-EspFiles')
    assert removal.index('Copy-Item') < removal.index('Remove-Item')


def test_the_boot_entry_is_still_detached_from_bcdedit():
    # CU-20261028-009, now in New-ShimEntry: no optional data, no BCD object
    b = body(INSTALL, 'New-ShimEntry')
    assert b.index('displayorder $id /addlast') < b.index('Repair-BootEntry -Description $script:EntryName -BcdId $id')
    assert "entryId = $null" in body(SCRIPT, 'Invoke-Install')


def test_boot_order_writes_are_verified():
    b = body(FW, 'Set-BootEntryPosition')
    assert b.index("Set-FirmwareVariable -Name 'BootOrder'") < b.index("throw 'BootOrder was not written as expected'")
