"""Check local third-party files and builds against the pinned hashes in manifest.json.

@module kachow.manifest
@description Load third_party/manifest.json and compare each pinned file under local/
(shim, MokManager, NVIDIA firmware) and each built EFI image with its recorded SHA-256.
@input Path manifest, Path local root (or a build directory for build hashes)
@output list[FileCheck] - one result per pinned file: ok, missing or mismatch
@dependencies hashlib, json, pathlib (stdlib)

@example
    all(c.ok for c in verify_files(load(Path("third_party/manifest.json")), Path("local")))
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

CHUNK = 1 << 20  # pragma: no mutate - any positive read size gives the same digest


@dataclass(frozen=True)
class FileCheck:
    path: str
    expected: str
    actual: str

    @property
    def ok(self):
        return self.actual == self.expected

    @property
    def state(self):
        if self.ok:
            return 'ok'
        return 'missing' if not self.actual else 'MISMATCH'


def load(path):
    data = json.loads(Path(path).read_text())
    for key in ('upstream', 'files', 'builds'):
        if key not in data:
            raise ValueError(f'manifest has no "{key}" section')
    return data


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(CHUNK), b''):
            h.update(chunk)
    return h.hexdigest()


def _check(root, rel, expected):
    p = Path(root) / rel
    return FileCheck(rel, expected, sha256_file(p) if p.is_file() else '')


def verify_files(manifest, root):
    return [_check(root, rel, meta['sha256']) for rel, meta in manifest['files'].items()]


def verify_builds(manifest, build_dir, names=None):
    names = names or list(manifest['builds'])
    return [_check(build_dir, f'{n}.EFI', manifest['builds'][n]) for n in names]
