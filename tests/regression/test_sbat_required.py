"""Regression test CU-20261028-001: shim 15.4+ refuses a second stage without .sbat even
when its key is enrolled (hardware boot, 2026-10-28). Every signed image the build makes
must carry .sbat, and the deploy guard must refuse a signed image without it."""
from pathlib import Path

import pytest

from peimage import build_pe, build_pe_with_cert
from kachow import sbat, signature

REPO = Path(__file__).resolve().parents[2]
SIGNED = REPO / 'local' / 'build' / 'signed'


def test_guard_refuses_pre_sbat_signed_image():
    cert = b'\x30\x82MOK'
    image = build_pe_with_cert(build_pe(), b'p7' + cert)
    assert signature.check(image, cert).reason == 'signed, but has no .sbat section'


def test_sbat_names_the_shim_generation_and_the_component():
    lines = sbat.SBAT.decode().splitlines()
    assert lines[0].split(',')[:2] == ['sbat', '1']
    assert lines[1].split(',')[:2] == ['tensor-unlock', '1']


@pytest.mark.parametrize('variant', ['auto', 'manual', 'dryrun', 'reltest'])
def test_built_signed_images_have_sbat_and_mok_signature(variant):
    image, cer = SIGNED / f'{variant}-grubx64.efi', REPO / 'local' / 'keys' / 'MOK.cer'
    if not (image.exists() and cer.exists()):
        pytest.skip('no local build (run bin/build.ps1)')
    c = signature.check(image.read_bytes(), cer.read_bytes())
    assert c.ok, c.reason
