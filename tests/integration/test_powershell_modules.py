"""Integration tests: load the src/windows PowerShell modules in Windows PowerShell 5.1 and
exercise the parts that need no elevation (drive-letter choice, Boot#### parsing)."""
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / 'src' / 'windows'
PS = shutil.which('powershell') or shutil.which('pwsh')

pytestmark = pytest.mark.skipif(PS is None, reason='no PowerShell on this machine')


def ps(script):
    r = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_free_drive_letter_skips_used_letters():
    out = ps(f"Import-Module '{WIN / 'Esp.psm1'}'; "
             "Get-FreeDriveLetter -Used @('Z','Y'); '|'; Get-FreeDriveLetter -Used @();"
             "'|'; $n = Get-FreeDriveLetter -Used ([char[]]'ZYXWVUTSRQPONMLKJIHGFED' | % { [string]$_ }); "
             "if ($null -eq $n) { 'none' }")
    assert [s.strip() for s in out.split('|')] == ['X', 'Z', 'none']


def load_option(desc, path_len, optional):
    body = desc.encode('utf-16-le') + b'\0\0'
    return struct.pack('<IH', 1, path_len) + body + b'\x7f' * path_len + optional


def test_load_option_parsing_finds_optional_data():
    data = load_option('Tensor Unlock (shim)', 20, b'WINDOWS' + b'\0' * 129)
    hexdata = ','.join(str(b) for b in data)
    out = ps(f"Import-Module '{WIN / 'FirmwareVars.psm1'}'; "
             f"$o = ConvertFrom-LoadOption ([byte[]]@({hexdata})); "
             "'{0}|{1}|{2}' -f $o.Description, $o.PathEnd, $o.OptionalDataLen")
    desc, end, opt = out.split('|')
    assert desc == 'Tensor Unlock (shim)'
    assert int(end) == 6 + 2 * len('Tensor Unlock (shim)') + 2 + 20
    assert int(opt) == 136


def test_project_paths_resolve_to_this_repository():
    out = ps(f"Import-Module '{WIN / 'Project.psm1'}'; Get-ProjectRoot; Get-LocalPath 'keys\\MOK.cer'")
    root, cer = out.splitlines()
    assert Path(root) == REPO
    assert Path(cer) == REPO / 'local' / 'keys' / 'MOK.cer'


def test_invoke_kachow_passes_exit_codes():
    fixture = REPO / 'tests' / 'fixtures' / 'RUN0003-dryrun.excerpt.txt'
    out = ps(f"Import-Module '{WIN / 'Project.psm1'}'; "
             f"$c = Invoke-Kachow -Arguments @('runlog', '{fixture}'); \"code=$c\"; "
             "try { Invoke-Kachow -Arguments @('runlog', 'C:\\nope\\missing.txt') } catch { 'threw' }")
    assert 'status=dryrun' in out and 'code=0' in out and out.endswith('threw')
