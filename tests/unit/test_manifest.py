"""Unit tests for kachow.manifest (pinned hash checks)."""
import hashlib
import json
from pathlib import Path

import pytest

from kachow import manifest

REPO = Path(__file__).resolve().parents[2]


def _write_manifest(tmp_path, files, builds=None):
    m = {'upstream': {'commit': 'abc'}, 'files': files, 'builds': builds or {}}
    p = tmp_path / 'manifest.json'
    p.write_text(json.dumps(m))
    return p


def test_verify_files_reports_ok_missing_and_mismatch(tmp_path):
    (tmp_path / 'efi').mkdir()
    (tmp_path / 'efi' / 'good.efi').write_bytes(b'good')
    (tmp_path / 'efi' / 'bad.efi').write_bytes(b'tampered')
    files = {'efi/good.efi': {'sha256': hashlib.sha256(b'good').hexdigest()},
             'efi/bad.efi': {'sha256': hashlib.sha256(b'original').hexdigest()},
             'efi/gone.efi': {'sha256': '00' * 32}}
    m = manifest.load(_write_manifest(tmp_path, files))
    states = {c.path: c.state for c in manifest.verify_files(m, tmp_path)}
    assert states == {'efi/good.efi': 'ok', 'efi/bad.efi': 'MISMATCH', 'efi/gone.efi': 'missing'}


def test_verify_builds_checks_named_or_all(tmp_path):
    (tmp_path / 'A.EFI').write_bytes(b'a')
    builds = {'A': hashlib.sha256(b'a').hexdigest(), 'B': '11' * 32}
    m = manifest.load(_write_manifest(tmp_path, {}, builds))
    assert [c.ok for c in manifest.verify_builds(m, tmp_path)] == [True, False]
    assert [c.path for c in manifest.verify_builds(m, tmp_path, ['A'])] == ['A.EFI']


def test_sha256_file_streams_large_files(tmp_path):
    p = tmp_path / 'big'
    blob = b'\xab' * ((1 << 20) + 7)
    p.write_bytes(blob)
    assert manifest.sha256_file(p) == hashlib.sha256(blob).hexdigest()


@pytest.mark.parametrize('missing', ['upstream', 'files', 'builds'])
def test_load_rejects_incomplete_manifest(tmp_path, missing):
    m = {'upstream': {}, 'files': {}, 'builds': {}}
    del m[missing]
    p = tmp_path / 'm.json'
    p.write_text(json.dumps(m))
    with pytest.raises(ValueError, match=missing):
        manifest.load(p)


def test_repository_manifest_pins_every_asset_the_installer_copies():
    m = manifest.load(REPO / 'third_party' / 'manifest.json')
    assert set(m['builds']) == {'UNLOCK4090', 'UNLOCK4090M', 'DRYRUN4090', 'RELTEST4090'}
    assert {'efi/shimx64.efi', 'efi/mmx64.efi'} <= set(m['files'])
    assert sum(1 for k in m['files'] if k.endswith('.bin')) == 5
    assert len(m['upstream']['commit']) == 40
    assert all(len(v['sha256']) == 64 for v in m['files'].values())
