"""Unit tests for kachow.cli (dispatch, exit codes, output)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from peimage import build_pe
from kachow import cli, mok, sbat

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / 'tests' / 'fixtures'


def test_sbat_command_writes_output(tmp_path, capsys):
    src, dst = tmp_path / 'in.efi', tmp_path / 'out.efi'
    src.write_bytes(build_pe())
    assert cli.main(['sbat', str(src), str(dst)]) == 0
    assert sbat.read_sbat(dst.read_bytes()) == sbat.SBAT
    assert '.sbat added (191 bytes)' in capsys.readouterr().out


def test_sbat_command_reports_refusal_as_usage_error(tmp_path, capsys):
    src = tmp_path / 'in.efi'
    src.write_bytes(build_pe(cert=b'sig'))
    assert cli.main(['sbat', str(src), str(tmp_path / 'o')]) == 2
    assert 'already signed' in capsys.readouterr().err


def test_check_signed_exit_codes(tmp_path, capsys):
    cert = tmp_path / 'c.cer'
    cert.write_bytes(b'CERT')
    img = tmp_path / 'i.efi'
    img.write_bytes(sbat.add_sbat(build_pe()))
    assert cli.main(['check-signed', str(img), '--cert', str(cert)]) == 1
    assert 'not signed' in capsys.readouterr().out


def test_missing_file_is_usage_error(tmp_path, capsys):
    assert cli.main(['check-signed', str(tmp_path / 'nope.efi'), '--cert', str(tmp_path / 'c')]) == 2
    assert 'kachow check-signed:' in capsys.readouterr().err


def test_mok_payload_command(tmp_path, capsys):
    cert = tmp_path / 'c.cer'
    cert.write_bytes(b'\x30DER')
    assert cli.main(['mok-payload', str(cert), str(tmp_path / 'm'), '--password', 'tensor']) == 0
    assert (tmp_path / 'm' / 'MokNew.bin').read_bytes() == mok.signature_list(b'\x30DER')
    assert '(32 bytes)' in capsys.readouterr().out


@pytest.mark.parametrize('fixture, code, status', [('RUN0018-auto-unlocked.txt', 0, 'unlocked'),
                                                   ('RUN0003-dryrun.excerpt.txt', 0, 'dryrun')])
def test_runlog_command(fixture, code, status, capsys):
    assert cli.main(['runlog', str(FIX / fixture)]) == code
    assert capsys.readouterr().out.startswith(f'status={status} ')


def test_runlog_reads_stdin_and_fails_when_not_unlocked(monkeypatch, capsys):
    import io
    monkeypatch.setattr('sys.stdin', io.StringIO('build=auto\nchoice: windows\n'))
    assert cli.main(['runlog', '-']) == 1
    assert 'status=not-unlocked' in capsys.readouterr().out


def test_verify_command_files_and_builds(tmp_path, capsys):
    (tmp_path / 'a.bin').write_bytes(b'a')
    (tmp_path / 'X.EFI').write_bytes(b'x')
    m = tmp_path / 'm.json'
    m.write_text(json.dumps({'upstream': {}, 'files': {'a.bin': {'sha256': hashlib.sha256(b'a').hexdigest()}},
                             'builds': {'X': '00' * 32}}))
    assert cli.main(['verify', '--manifest', str(m), '--root', str(tmp_path)]) == 0
    assert cli.main(['verify', '--manifest', str(m), '--builds', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'ok       a.bin' in out and 'MISMATCH X.EFI' in out


def test_build_command_rejects_unknown_variant():
    with pytest.raises(SystemExit):
        cli.main(['build', 'repo', 'zig', 'out', 'NOPE'])


def test_build_command_prints_each_image(tmp_path, monkeypatch, capsys):
    from kachow import zigbuild
    monkeypatch.setattr(zigbuild, 'build', lambda repo, zig, out, names: [
        zigbuild.Built(Path(out) / 'DRYRUN4090.EFI', 3, 'ab' * 32)])
    assert cli.main(['build', 'r', 'zig', str(tmp_path), 'DRYRUN4090']) == 0
    assert capsys.readouterr().out.strip() == f'DRYRUN4090.EFI 3 {"ab" * 32}'


def test_entry_script_runs_isolated():
    r = subprocess.run([sys.executable, '-I', str(REPO / 'bin' / 'kachow.py'), 'runlog',
                        str(FIX / 'RUN0018-auto-unlocked.txt')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith('status=unlocked')


def test_check_signed_accepts_a_mok_signed_image(tmp_path, capsys):
    from peimage import build_pe_with_cert
    cert = tmp_path / 'c.cer'
    cert.write_bytes(b'\x30\x82MOK-DER')
    img = tmp_path / 'i.efi'
    img.write_bytes(build_pe_with_cert(sbat.add_sbat(build_pe()), b'p7' + b'\x30\x82MOK-DER' + b'p7'))
    assert cli.main(['check-signed', str(img), '--cert', str(cert)]) == 0
    assert capsys.readouterr().out.strip() == f'{img}: ok'


@pytest.mark.parametrize('variants, names', [(['DRYRUN4090'], ['DRYRUN4090']), ([], None)])
def test_build_command_passes_the_chosen_variants(variants, names, tmp_path, monkeypatch):
    from kachow import zigbuild
    seen = []
    monkeypatch.setattr(zigbuild, 'build', lambda repo, zig, out, n: seen.append(n) or [])
    assert cli.main(['build', 'r', 'zig', str(tmp_path), *variants]) == 0
    assert seen == [names]


def test_verify_builds_checks_only_the_named_images(tmp_path, capsys):
    (tmp_path / 'X.EFI').write_bytes(b'x')
    m = tmp_path / 'm.json'
    m.write_text(json.dumps({'upstream': {}, 'files': {},
                             'builds': {'X': hashlib.sha256(b'x').hexdigest(), 'Y': '00' * 32}}))
    assert cli.main(['verify', '--manifest', str(m), '--builds', str(tmp_path), 'X']) == 0
    assert capsys.readouterr().out.splitlines() == ['ok       X.EFI']


@pytest.mark.parametrize('locked, code', [(True, 1), (False, 0)])
def test_bench_command_reports_and_sets_the_exit_code(locked, code, monkeypatch, capsys):
    import functools

    from faketorch import fake_torch
    from kachow.bench import gemm
    monkeypatch.setattr(gemm, 'measure', functools.partial(gemm.measure, pause=0, sleep=lambda s: None))
    a = cli.parser().parse_args(['bench', '--size', '8', '--iters', '1', '--rounds', '1'])
    assert cli.cmd_bench(a, torch=fake_torch(locked=locked)) == code
    out = capsys.readouterr().out
    assert out.startswith('Fake GPU 0  torch fake  8^3 x 1, best of 1\n')
    assert ('UNLOCKED' in out) is not locked


def test_parser_defaults_point_into_the_repository():
    p = cli.parser()
    assert p.description == 'Command dispatcher: `kachow <command> [args]`, one command per module.'
    assert p.parse_args(['check-signed', 'i']).cert == str(REPO / 'local' / 'keys' / 'MOK.cer')
    v = p.parse_args(['verify'])
    assert (v.manifest, v.root, v.builds, v.names) == (str(REPO / 'third_party' / 'manifest.json'),
                                                       str(REPO / 'local'), None, [])
    b = p.parse_args(['bench'])
    assert (b.size, b.iters, b.rounds) == (8192, 50, 3)
    assert p.parse_args(['banner', 'o']).art == str(REPO / 'config' / 'banner.txt')


def test_banner_command_writes_files_and_shows_the_ascii_copy(tmp_path, capsys):
    art = tmp_path / 'art.txt'
    art.write_text('⣿⠀A\n', encoding='utf-8')
    assert cli.main(['banner', str(tmp_path / 'out'), '--art', str(art)]) == 0
    out = capsys.readouterr().out
    assert f"{tmp_path / 'out' / 'banner.txt'} (14 bytes)" in out
    assert out.endswith('lacks a glyph):\n# A\n')
    assert (tmp_path / 'out' / 'banner-ascii.txt').read_bytes() == '# A\r\n\r\n'.encode('utf-16-le')


def test_banner_command_reports_bad_art_as_usage_error(tmp_path, capsys):
    art = tmp_path / 'art.txt'
    art.write_text('x' * 80, encoding='utf-8')
    assert cli.main(['banner', str(tmp_path / 'out'), '--art', str(art)]) == 2
    assert '80 columns' in capsys.readouterr().err


@pytest.mark.parametrize('argv', [[], ['mok-payload', 'c', 'o'], ['banner'], ['next-step']])
def test_required_arguments_are_enforced(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2


def test_runlog_json_has_every_fact(capsys):
    import json
    assert cli.main(['runlog', str(FIX / 'RUN0018-auto-unlocked.txt'), '--json']) == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts['status'] == 'unlocked' and facts['via_shim'] is True and facts['post_gop'] == [0x88888888, 8]
    assert facts['skip_stage'] == '' and facts['build'] == 'auto'


@pytest.mark.parametrize('argv, action, phase', [
    (['--phase', 'trial', '--log', 'RUN0003-dryrun.excerpt.txt'], 'stop', 'failed'),   # the excerpt has no "Checks passed."
    (['--phase', 'unlock', '--log', 'RUN0018-auto-unlocked.txt'], 'finish', 'installed'),
    (['--phase', 'trial', '--mok-pending'], 'retry', 'trial'),
    (['--phase', 'unlock', '--attempts', '2'], 'stop', 'failed'),
])
def test_next_step_command_prints_the_step(argv, action, phase, capsys):
    import json
    argv = [str(FIX / a) if a.endswith('.txt') else a for a in argv]
    assert cli.main(['next-step', *argv]) == 0
    step = json.loads(capsys.readouterr().out)
    assert (step['action'], step['phase']) == (action, phase) and step['message']


def test_next_step_passes_both_boot_facts(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli.lifecycle, 'next_step', lambda *a: seen.append(a) or cli.lifecycle.Step('x', 'y', 'z'))
    assert cli.main(['next-step', '--phase', 'trial', '--via-entry', '--mok-pending', '--attempts', '1']) == 0
    assert seen == [('trial', None, 1, True, True)]
    assert cli.main(['next-step', '--phase', 'unlock']) == 0
    assert seen[1] == ('unlock', None, 0, False, False)


def test_next_step_rejects_an_unknown_phase(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(['next-step', '--phase', 'installed'])
    assert e.value.code == 2
