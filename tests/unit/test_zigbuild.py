"""Unit tests for kachow.zigbuild (zig command construction and build loop)."""
import hashlib
from pathlib import Path

import pytest

from kachow import zigbuild


def test_compile_command_carries_upstream_flags_and_variant_defines(tmp_path):
    cmd = zigbuild.compile_command('zig', 'UNLOCK4090M', 'vendor/unlock_610', tmp_path)
    assert cmd[:2] == ['zig', 'cc']
    assert list(zigbuild.COMMON) == cmd[2:2 + len(zigbuild.COMMON)]
    assert '-DGU_MANUAL' in cmd and '-DGU_AD104_TRANSACTION' in cmd
    assert '-DGU_BUILD_ID="manual"' in cmd
    assert cmd[-4:] == ['-c', 'vendor/unlock_610.c', '-o',
                        str(tmp_path / 'obj' / 'UNLOCK4090M-vendor_unlock_610.o')]


def test_link_command_is_reproducible_and_lists_every_object(tmp_path):
    cmd = zigbuild.link_command('zig', 'DRYRUN4090', tmp_path)
    assert '-Wl,/Brepro' in cmd and '-nostdlib' in cmd and '-s' in cmd
    objs = [c for c in cmd if c.endswith('.o')]
    assert len(objs) == len(zigbuild.SOURCES) == 15
    assert cmd[-2:] == ['-o', str(tmp_path / 'DRYRUN4090.EFI')]


@pytest.mark.parametrize('build_id, name', [('auto', 'UNLOCK4090'), ('manual', 'UNLOCK4090M'),
                                            ('dryrun', 'DRYRUN4090'), ('reltest', 'RELTEST4090')])
def test_variant_for_maps_build_ids(build_id, name):
    assert zigbuild.variant_for(build_id) == name


def test_variant_for_rejects_unknown_id():
    with pytest.raises(KeyError, match='unknown build id'):
        zigbuild.variant_for('turbo')


def test_only_dryrun_variants_close_the_write_gates():
    for name, (_ident, defines) in zigbuild.VARIANTS.items():
        writes = '-DGU_4090_DRYRUN' not in defines
        assert writes == (name in ('UNLOCK4090', 'UNLOCK4090M'))


class FakeZig:
    """Records commands; the link step writes a stand-in image plus the extras zig leaves."""

    def __init__(self):
        self.calls = []

    def __call__(self, cmd, check, cwd):
        assert check is True
        self.calls.append((cmd, cwd))
        out = Path(cmd[-1])
        if out.suffix == '.EFI':
            out.write_bytes(b'image:' + out.stem.encode())
            out.with_suffix('.pdb').write_bytes(b'pdb')
            out.with_suffix('.lib').write_bytes(b'lib')


def test_build_runs_compile_then_link_and_hashes_output(tmp_path):
    zig = FakeZig()
    built = zigbuild.build(tmp_path / 'repo', 'zig', tmp_path / 'out', ['UNLOCK4090'], run=zig)
    assert len(zig.calls) == 16
    assert all(cwd == (tmp_path / 'repo').resolve() for _c, cwd in zig.calls)
    assert zig.calls[-1][0][-1].endswith('UNLOCK4090.EFI')
    (b,) = built
    assert b.path == (tmp_path / 'out' / 'UNLOCK4090.EFI').resolve()
    assert b.size == len(b'image:UNLOCK4090')
    assert b.sha256 == hashlib.sha256(b'image:UNLOCK4090').hexdigest()
    assert not (tmp_path / 'out' / 'UNLOCK4090.pdb').exists()
    assert not (tmp_path / 'out' / 'UNLOCK4090.lib').exists()


def test_build_defaults_to_all_variants(tmp_path):
    built = zigbuild.build(tmp_path, 'zig', tmp_path / 'out', run=FakeZig())
    assert [b.path.stem for b in built] == list(zigbuild.VARIANTS)


def test_build_rejects_unknown_variant_before_running(tmp_path):
    zig = FakeZig()
    with pytest.raises(KeyError):
        zigbuild.build(tmp_path, 'zig', tmp_path / 'out', ['UNLOCK4090', 'NOPE'], run=zig)
    assert zig.calls == []


def test_variant_for_compares_by_value():
    assert zigbuild.variant_for(''.join(['au', 'to'])) == 'UNLOCK4090'


def test_build_creates_the_output_tree_and_tolerates_absent_extras(tmp_path):
    def link_only(cmd, check, cwd):              # writes the image, no .pdb or .lib
        if cmd[-1].endswith('.EFI'):
            Path(cmd[-1]).write_bytes(b'img')
    for _ in range(2):                           # the second build reuses the existing tree
        (b,) = zigbuild.build(tmp_path, 'zig', tmp_path / 'new' / 'out', ['DRYRUN4090'], run=link_only)
    assert (tmp_path / 'new' / 'out' / 'obj').is_dir() and b.size == 3
