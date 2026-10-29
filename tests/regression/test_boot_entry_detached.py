"""Regression test CU-20261028-009 (boot entry detached from bcdedit): the shim entry must
carry no optional data (shim reads it as a file name and prints "Failed to open") and must
have no BCD object (the next bcdedit sync re-creates the entry with the blob). New-ShimEntry
(kachow.ps1 install) and adopting an older install do both through Repair-BootEntry;
uninstall removes the entry through the firmware variables, since bcdedit no longer owns it.
(install.ps1, fix-bootentry.ps1 and rollback.ps1 were folded into these by CU-20261028-012.)"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FW = (REPO / 'src' / 'windows' / 'FirmwareVars.psm1').read_text()


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_repair_strips_before_deleting_the_bcd_object():
    b = body(FW, 'Repair-BootEntry')
    assert b.index('Clear-BootEntryOptionalData') < b.index('bcdedit /delete $BcdId /f')
    # entries the sync re-created with the blob are removed, and exactly one must remain
    assert 'Remove-BootEntry -Entry $dups[0]' in b and '$left.Count -ne 1' in b


def test_strip_keeps_only_the_load_option_up_to_its_path():
    b = body(FW, 'Clear-BootEntryOptionalData')
    assert '[0..($Entry.Opt.PathEnd - 1)]' in b and '$after.Data.Length -ne $Entry.Opt.PathEnd' in b


def test_remove_never_empties_boot_order():
    b = body(FW, 'Remove-BootEntry')
    assert '$keep.Count -eq 0' in b
    assert b.index("-Name 'BootOrder'") < b.index('-Name $Entry.Name -Value $null')


def test_install_detaches_the_new_entry_and_records_no_bcd_id():
    install = (REPO / 'src' / 'windows' / 'Install.psm1').read_text()
    b = body(install, 'New-ShimEntry')
    assert 'Repair-BootEntry -Description $script:EntryName -BcdId $id' in b
    assert b.index('displayorder $id /addlast') < b.index('Repair-BootEntry')
    assert 'entryId = $null' in (REPO / 'bin' / 'kachow.ps1').read_text()


def test_adopting_an_old_install_applies_the_repair_and_updates_the_record():
    # what fix-bootentry.ps1 did, now done when install adopts an install made before kachow.ps1
    b = body((REPO / 'bin' / 'kachow.ps1').read_text(), 'Invoke-Adopt')
    assert "Repair-BootEntry -Description $entry.Opt.Description -BcdId $Rec['entryId']" in b
    assert '$Rec.entryId = $null' in b
    assert b.index("$facts.status -ne 'unlocked'") < b.index('Repair-BootEntry')


def test_uninstall_removes_the_firmware_entry_itself():
    b = body((REPO / 'src' / 'windows' / 'Install.psm1').read_text(), 'Remove-ShimEntries')
    assert 'Get-ShimEntry' in b and 'Remove-BootEntry -Entry $e' in b
    assert b.index('bcdedit /delete') < b.index('Remove-BootEntry')
