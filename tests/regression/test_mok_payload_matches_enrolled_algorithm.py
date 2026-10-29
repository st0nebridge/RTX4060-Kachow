"""Regression test CU-20261028-004: stage-mok moved its MokNew/MokAuth construction from
PowerShell to kachow.mok. The PowerShell algorithm below is the one that staged the
key MokManager enrolled on 2026-10-28; the Python payload must match it byte for byte."""
import shutil
import subprocess
from pathlib import Path

import pytest

from kachow import mok

PS = shutil.which('powershell')
ORIGINAL = r"""
$cer = [IO.File]::ReadAllBytes('{cert}')
$certX509 = [Guid]'a5c059a1-94e4-4aa7-87b5-ab155c2bf072'
$owner = [Guid]'605dab50-e046-4300-abb6-3dd810dd8b23'
$ms = New-Object IO.MemoryStream
$w = New-Object IO.BinaryWriter $ms
$w.Write($certX509.ToByteArray())
$w.Write([uint32](28 + 16 + $cer.Length))
$w.Write([uint32]0)
$w.Write([uint32](16 + $cer.Length))
$w.Write($owner.ToByteArray())
$w.Write($cer)
$w.Flush()
$esl = $ms.ToArray()
$sha = [Security.Cryptography.SHA256]::Create()
$pw = [Text.Encoding]::Unicode.GetBytes('{password}')
$auth = $sha.ComputeHash([byte[]]($esl + $pw))
[BitConverter]::ToString($esl).Replace('-', '')
[BitConverter]::ToString($auth).Replace('-', '')
"""


@pytest.mark.skipif(PS is None, reason='needs Windows PowerShell')
@pytest.mark.parametrize('password', ['tensor', 'hunter2'])
def test_python_payload_equals_original_powershell(tmp_path, password):
    cert = tmp_path / 'test.cer'
    cert.write_bytes(bytes.fromhex('3082') + bytes(range(256)) * 3)
    script = ORIGINAL.replace('{cert}', str(cert)).replace('{password}', password)
    r = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    esl_hex, auth_hex = r.stdout.split()
    req = mok.request(cert.read_bytes(), password)
    assert req.mok_new == bytes.fromhex(esl_hex)
    assert req.mok_auth == bytes.fromhex(auth_hex)


def test_enrolled_certificate_payload_size():
    cer = Path(__file__).resolve().parents[2] / 'local' / 'keys' / 'MOK.cer'
    if not cer.exists():
        pytest.skip('no local MOK.cer')
    # stage-mok reported "MokNew staged: 900 bytes" for the 856-byte certificate
    assert len(mok.request(cer.read_bytes(), 'tensor').mok_new) == 28 + 16 + 856
