"""Regression test CU-20261028-002: an unsigned grubx64.efi reached the ESP (re-sign.ps1
was cut short by a pipe) and shim stopped with "Security Violation (0x1A)". Every script
that writes grubx64.efi must pass Assert-MokSigned first, and signing must verify."""
import re
from pathlib import Path

from peimage import build_pe
from kachow import cli, sbat

REPO = Path(__file__).resolve().parents[2]
BIN = REPO / 'bin'


def test_check_signed_fails_an_unsigned_image(tmp_path):
    img, cer = tmp_path / 'grubx64.efi', tmp_path / 'MOK.cer'
    img.write_bytes(sbat.add_sbat(build_pe()))
    cer.write_bytes(b'\x30\x82MOK')
    assert cli.main(['check-signed', str(img), '--cert', str(cer)]) == 1


def test_every_writer_of_grubx64_asserts_the_signature_before_copying():
    # Install.psm1 is the only code that writes \EFI\tensor-unlock\grubx64.efi (kachow.ps1
    # and deploy.ps1 call it), and every image it copies comes from Get-UnlockerImage.
    scripts = list(BIN.glob('*.ps1')) + list((REPO / 'src' / 'windows').glob('*.psm1'))
    # a path ending in grubx64.efi; "<variant>-grubx64.efi" is a local build output, not the ESP
    writers = [p for p in scripts if re.search(r"(?<!-)grubx64\.efi['\"]\)", p.read_text())]
    assert [p.name for p in writers] == ['Install.psm1']
    text = writers[0].read_text()
    get = re.search(r'function Get-UnlockerImage.*?\n}', text, re.S).group(0)
    assert get.index('Assert-MokSigned $path') < get.index('\n    $path\n')   # checked, then returned
    for name in ('Install-EspFiles', 'Set-EspUnlocker'):
        body = re.search(rf'function {name}.*?\n}}', text, re.S).group(0)
        assert body.index('$image = Get-UnlockerImage $Variant') < body.index('Copy-Verified $image'), name


def test_signing_verifies_its_own_output():
    text = (REPO / 'src' / 'windows' / 'Signing.psm1').read_text()
    body = re.search(r'function Set-MokSignature.*?\n}', text, re.S).group(0)
    assert body.index('Set-AuthenticodeSignature') < body.index('Assert-MokSigned')
    assert '| Select-Object -First' not in text


def test_no_script_truncates_a_pipeline_with_select_first():
    # Select-Object -First stops the upstream command in Windows PowerShell 5.1.
    for p in list(BIN.glob('*.ps1')) + list((REPO / 'src' / 'windows').glob('*.psm1')):
        assert 'Select-Object -First' not in p.read_text(), p.name
