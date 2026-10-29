"""Regression test CU-20261028-001 (source patch): the unlocker refuses Secure Boot unless
started through shim (SHIM_LOCK protocol present), and the console splitter's path-less
GOP is attributed rather than refused. The patch must keep those hunks and apply to the
pinned upstream commit."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kachow import mok

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / 'patches' / 'secureboot-shim.patch'
UPSTREAM = REPO / 'local' / 'upstream'


def added_lines():
    return [ln[1:] for ln in PATCH.read_text().splitlines() if ln.startswith('+') and not ln.startswith('+++')]


def test_patch_declares_the_shim_lock_guid():
    g = mok.SHIM_LOCK_GUID
    want = f'{{0x{g.hex[:8]},0x{g.hex[8:12]},0x{g.hex[12:16]},'
    assert any('ShimLockGuid' in ln and want in ln for ln in added_lines())


def test_secure_boot_is_accepted_only_with_shim_lock_present():
    text = '\n'.join(added_lines())
    assert 'LocateProtocol(&ShimLockGuid' in text
    assert 'else s=EFI_SECURITY_VIOLATION;' in text


def test_gop_attribution_helpers_are_present():
    text = '\n'.join(added_lines())
    for fn in ('Mirror(', 'StaleOwnScreen(', 'LogGops('):
        assert fn in text, fn


def test_patch_touches_only_app_and_release():
    files = [ln.split()[1] for ln in PATCH.read_text().splitlines() if ln.startswith('+++ ')]
    assert files == ['b/app.c', 'b/release.c']


@pytest.mark.skipif(not (UPSTREAM / '.git').exists() or shutil.which('git') is None,
                    reason='no local upstream checkout')
def test_patch_applies_to_pinned_upstream():
    commit = json.loads((REPO / 'third_party' / 'manifest.json').read_text())['upstream']['commit']
    head = subprocess.run(['git', '-C', str(UPSTREAM), 'rev-parse', commit], capture_output=True, text=True)
    assert head.returncode == 0 and head.stdout.strip() == commit
    work = subprocess.run(['git', '-C', str(UPSTREAM), 'apply', '--check', str(PATCH)],
                          capture_output=True, text=True)
    assert work.returncode == 0, work.stderr
