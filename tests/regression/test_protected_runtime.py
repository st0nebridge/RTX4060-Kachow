"""Regression test CU-20261029-003 (security review 2026-10-29, H-1 and M-1).

M-1: the SYSTEM keeper task and the elevated logon task ran scripts and a python.exe that
non-admin accounts could modify (Authenticated Users inherited Modify on the checkout folder;
Python in the user profile). The tasks now run only from a copy under Program Files
that only Administrators and SYSTEM can write (owner Administrators, inheritance off), with
its own copy of a PSF-signed Python and its own state, and refuse to register from anywhere
else. H-1: MOK.key and MOK.pfx were readable by every local account; they are now readable
only by Administrators and SYSTEM, and verification reads only the public MOK.cer."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / 'src' / 'windows'
RUNTIME = (WIN / 'Runtime.psm1').read_text('utf-8')
MACHINE = (WIN / 'Machine.psm1').read_text('utf-8')
SIGNING = (WIN / 'Signing.psm1').read_text('utf-8')
PROJECT = (WIN / 'Project.psm1').read_text('utf-8')
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
BUILD = (REPO / 'bin' / 'build.ps1').read_text('utf-8')


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_the_protected_acl_is_admin_and_system_only():
    b = body(RUNTIME, 'Protect-AdminOnly')
    assert '/inheritance:r' in b and '/setowner' in b and '*S-1-5-32-544' in b
    assert '*S-1-5-32-544:' in b and '*S-1-5-18:' in b
    assert '*S-1-5-32-545:' in b and '[switch]$NoRead' in b   # Users may read and run, never write
    assert 'S-1-5-11' not in RUNTIME                       # never Authenticated Users


def test_the_runtime_lives_under_program_files_and_is_protected_after_copying():
    assert "Join-Path $env:ProgramFiles 'RTX40 Ka-chow!'" in RUNTIME
    b = body(RUNTIME, 'Install-Runtime')
    assert b.index('Copy-PythonRuntime') < b.rindex('Protect-AdminOnly')
    for part in ('bin', 'src', 'config', 'third_party', 'build\\signed', 'efi', 'assets', 'MOK.cer'):
        assert part in b
    assert 'MOK.key' not in b and 'MOK.pfx' not in b and 'keys\\*' not in b


def test_python_is_copied_only_when_signed_by_the_psf_and_without_site_packages():
    b = body(RUNTIME, 'Copy-PythonRuntime')
    assert 'Get-AuthenticodeSignature' in b and 'Python Software Foundation' in b and "'Valid'" in b
    assert 'site-packages' in b


def test_tasks_register_only_from_the_protected_copy_and_use_its_python():
    for name in ('Register-KeeperTask', 'Register-LogonTask'):
        assert body(MACHINE, name).lstrip().split('\n')[1].strip() == 'Assert-InRuntime'
    keeper = body(MACHINE, 'Register-KeeperTask')
    assert "python\\python.exe" in keeper and 'Get-Command python' not in keeper
    assert "python\\python.exe" in body(PROJECT, 'Invoke-Kachow')


def test_every_command_runs_from_the_refreshed_protected_copy():
    assert 'Test-InRuntime' in SCRIPT and 'Install-Runtime' in SCRIPT
    hand = SCRIPT[SCRIPT.index('if (-not (Test-InRuntime))'):SCRIPT.index('$script:Pause = $Elevated')]
    assert 'Invoke-RuntimeCommand' in hand and 'Remove-Runtime' in hand
    assert "'install'" in hand and 'build.ps1' in hand


def test_already_installed_moves_its_tasks_onto_the_protected_copy():
    b = body(SCRIPT, 'Invoke-Install')
    installed = b[b.index("$rec['phase'] -eq 'installed'"):]
    assert 'Register-LogonTask' in installed.split('\n')[0] + installed.split('\n')[1]


def test_the_signing_key_is_admin_only_and_verification_uses_the_public_cert():
    assert "Protect-AdminOnly" in body(SIGNING, 'Protect-SigningKey') and '-NoRead' in body(SIGNING, 'Protect-SigningKey')
    for f in ('MOK.key', 'MOK.pfx'):
        assert f in body(SIGNING, 'Protect-SigningKey')
    assert "keys\\MOK.cer" in body(SIGNING, 'Get-MokCertificate') and 'MOK.pfx' not in body(SIGNING, 'Get-MokCertificate')
    assert 'Get-MokSigningCertificate' in body(SIGNING, 'Set-MokSignature')
    assert 'Protect-SigningKey' in BUILD and 'Protect-SigningKey' in SCRIPT
