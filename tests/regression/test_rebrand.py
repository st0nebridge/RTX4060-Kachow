"""Regression test CU-20261028-011 (rename to RTX40 Ka-chow!, since 0.2.1 RTX4060 Ka-chow! in
the docs and package metadata): the project, package, CLI
and PowerShell bridge carry the new name and nothing tracked still uses the old one, while
the names the firmware and an installed machine depend on are kept (D-20261028-012)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from kachow import cli

REPO = Path(__file__).resolve().parents[2]


def test_project_is_named_ka_chow():
    assert (REPO / 'README.md').read_text('utf-8').startswith('# RTX4060 Ka-chow!\n')
    assert 'name = "rtx4060-kachow"' in (REPO / 'pyproject.toml').read_text('utf-8')
    assert cli.parser().prog == 'kachow'


def test_entry_points_moved():
    assert (REPO / 'bin' / 'kachow.py').is_file() and not (REPO / 'bin' / 'rtxunlock.py').exists()
    assert (REPO / 'src' / 'kachow' / 'cli.py').is_file() and not (REPO / 'src' / 'rtxunlocker').exists()
    assert 'function Invoke-Kachow' in (REPO / 'src' / 'windows' / 'Project.psm1').read_text('utf-8')


@pytest.mark.skipif(not (REPO / '.git').exists() or shutil.which('git') is None, reason='not a git checkout')
def test_old_name_only_in_the_changelog():
    r = subprocess.run(['git', '-C', str(REPO), 'grep', '-lIi', 'rtxunlock', '--', '.',
                        ':!CHANGES.md', ':!tests/regression/test_rebrand.py'], capture_output=True, text=True)
    assert r.stdout == ''


def test_firmware_facing_names_are_kept():
    install = (REPO / 'src' / 'windows' / 'Install.psm1').read_text('utf-8')
    assert "$script:EntryName = 'Tensor Unlock (shim)'" in install
    assert "$script:EfiDir = 'EFI\\tensor-unlock'" in install
    assert 'GPU4090-ASSETS' in (REPO / 'patches' / 'start-banner.patch').read_text('utf-8')
