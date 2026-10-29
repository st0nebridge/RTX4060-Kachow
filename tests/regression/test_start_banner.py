r"""Regression test CU-20261028-008 (start-screen banner): the unlocker shows
\GPU4090-ASSETS\banner.txt before its first line, falls back to the ASCII copy when the
console cannot draw a glyph, refuses control characters and odd sizes, and never lets the
banner affect the run. The patch applies after secureboot-shim.patch to the pinned commit."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kachow import banner

REPO = Path(__file__).resolve().parents[2]
PATCH = REPO / 'patches' / 'start-banner.patch'
UPSTREAM = REPO / 'local' / 'upstream'
MANIFEST = json.loads((REPO / 'third_party' / 'manifest.json').read_text())


def added():
    return '\n'.join(ln[1:] for ln in PATCH.read_text().splitlines() if ln.startswith('+') and not ln.startswith('+++'))


def test_manifest_applies_both_patches_in_order():
    assert MANIFEST['upstream']['patches'] == ['patches/secureboot-shim.patch', 'patches/start-banner.patch']


def test_patch_touches_only_the_console_code():
    files = [ln.split()[1] for ln in PATCH.read_text().splitlines() if ln.startswith('+++ ')]
    assert files == ['b/app.c', 'b/boot_io.c', 'b/boot_io.h']


def test_banner_is_shown_before_the_first_console_line():
    hunk = PATCH.read_text().split('+++ b/app.c', 1)[1].split('--- a/', 1)[0]
    assert '+  GuBootBanner();\n   GuBootNote("RTX 4060 Laptop unlock (%s)\\n",GU_BUILD_ID);' in hunk


def test_banner_reads_the_files_kachow_writes():
    text = added()
    for name in banner.FILES:
        assert f'L"\\\\GPU4090-ASSETS\\\\{name}"' in text, name
    assert '#define BANNER_MAX 16384U' in text


def test_banner_validation_and_fallback():
    text = added()
    assert '(size&1)' in text                                  # whole UCS-2 characters only
    assert "(c<0x20&&c!=L'\\r'&&c!=L'\\n')" in text             # no control characters
    assert '(ascii&&c>0x7e)' in text                           # the copy really is ASCII
    assert '(c>=0xd800&&c<0xe000)' in text                     # no surrogates
    assert 'if(!Drawable(t))' in text and 'TestString(o,line)' in text


def test_banner_never_changes_the_run():
    text = added()
    assert 'VOID GuBootBanner(VOID)' in text and 'Gu.fault' not in text and 'goto' not in text


@pytest.mark.skipif(not (UPSTREAM / '.git').exists() or shutil.which('git') is None,
                    reason='no local upstream checkout')
def test_patches_apply_in_order_to_pinned_upstream(tmp_path):
    work = tmp_path / 'src'
    run = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True)  # noqa: E731
    assert run('clone', '-q', '--no-checkout', str(UPSTREAM), str(work)).returncode == 0
    assert run('-C', str(work), '-c', 'advice.detachedHead=false', 'checkout', '-q',
               MANIFEST['upstream']['commit']).returncode == 0
    for p in MANIFEST['upstream']['patches']:
        r = run('-C', str(work), 'apply', str(REPO / p))
        assert r.returncode == 0, (p, r.stderr)
