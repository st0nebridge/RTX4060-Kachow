"""Command dispatcher: `kachow <command> [args]`, one command per module.

@module kachow.cli
@description Route each subcommand to the module that owns it and turn its result into
output and an exit code (0 ok, 1 check failed, 2 usage error).
@input argv list[str]
@output int exit code; report text on stdout
@dependencies kachow.sbat, .signature, .zigbuild, .mok, .runlog, .lifecycle, .manifest, .banner, .bench,
    .keeper

@example
    kachow check-signed local/build/signed/auto-grubx64.efi --cert local/keys/MOK.cer
"""
import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

from . import banner, bench, keeper, lifecycle, manifest, mok, runlog, sbat, signature, zigbuild


def cmd_sbat(a):
    out = sbat.add_sbat(Path(a.input).read_bytes())
    Path(a.output).write_bytes(out)
    print(f'{a.output}: .sbat added ({len(sbat.SBAT)} bytes)')
    return 0


def cmd_check_signed(a):
    c = signature.check(Path(a.image).read_bytes(), Path(a.cert).read_bytes())
    print(f'{a.image}: {c.reason}')
    return 0 if c.ok else 1


def cmd_build(a):
    for b in zigbuild.build(a.repo, a.zig, a.out, a.variants or None):
        print(f'{b.path.name} {b.size} {b.sha256}')
    return 0


def cmd_mok_payload(a):
    new, auth = mok.request(Path(a.cert).read_bytes(), a.password).write(a.out)
    print(f'{new} ({new.stat().st_size} bytes)\n{auth} ({auth.stat().st_size} bytes)')
    return 0


def cmd_runlog(a):
    with a.log as f:
        log = runlog.parse(f.read())
    if a.json:
        print(json.dumps({**dataclasses.asdict(log), 'status': log.status}))
    else:
        print(runlog.summary(log))
    return 0 if log.status in ('unlocked', 'dryrun') else 1


def cmd_next_step(a):
    log = runlog.parse(Path(a.log).read_text(errors='replace')) if a.log else None
    step = lifecycle.next_step(a.phase, log, a.attempts, a.via_entry, a.mok_pending)
    print(json.dumps(dataclasses.asdict(step)))
    return 0


def cmd_verify(a):
    m = manifest.load(a.manifest)
    checks = manifest.verify_builds(m, a.builds, a.names or None) if a.builds else manifest.verify_files(m, a.root)
    for c in checks:
        print(f'{c.state:8s} {c.path}')
    return 0 if all(c.ok for c in checks) else 1


def cmd_banner(a):
    b = banner.parse(Path(a.art).read_text('utf-8'))
    for p in banner.write(b, a.out):
        print(f'{p} ({p.stat().st_size} bytes)')
    print(f'ASCII copy (shown when the firmware font lacks a glyph):\n{b.ascii}')
    return 0


def cmd_bench(a, torch=None):
    if torch is None:
        import torch  # pragma: no cover - needs torch with CUDA; tests pass a fake
    text, unlocked = bench.run(torch, a.size, a.iters, a.rounds)
    print(text)
    return 0 if unlocked else 1


def cmd_keep(a, load=keeper.load, **hold_args):
    log = Path(a.log)
    log.parent.mkdir(parents=True, exist_ok=True)

    def say(msg):
        with log.open('a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    try:
        keeper.hold(load(), say, **hold_args)
    except keeper.KeeperError as e:
        say(str(e))
        print(f'kachow keep: {e}', file=sys.stderr)
        return 1
    return 0


def parser():
    root = Path(__file__).resolve().parents[2]
    p = argparse.ArgumentParser(prog='kachow', description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)

    s = sub.add_parser('sbat', help='add an .sbat section to an unsigned EFI image')
    s.add_argument('input')
    s.add_argument('output')
    s.set_defaults(fn=cmd_sbat)

    s = sub.add_parser('check-signed', help='require MOK signature and .sbat (exit 1 otherwise)')
    s.add_argument('image')
    s.add_argument('--cert', default=str(root / 'local' / 'keys' / 'MOK.cer'))
    s.set_defaults(fn=cmd_check_signed)

    s = sub.add_parser('build', help='compile unlocker variants with zig')
    s.add_argument('repo')
    s.add_argument('zig')
    s.add_argument('out')
    s.add_argument('variants', nargs='*', choices=[*zigbuild.VARIANTS, []], metavar='VARIANT')
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser('mok-payload', help='write MokNew.bin and MokAuth.bin')
    s.add_argument('cert')
    s.add_argument('out')
    s.add_argument('--password', required=True)
    s.set_defaults(fn=cmd_mok_payload)

    s = sub.add_parser('runlog', help='summarise an unlocker RUNnnnn.TXT (- reads stdin)')
    s.add_argument('log', type=argparse.FileType('r', errors='replace'))
    s.add_argument('--json', action='store_true', help='every parsed fact as one JSON object')
    s.set_defaults(fn=cmd_runlog)

    s = sub.add_parser('next-step', help="the installer's next step after a boot (JSON)")
    s.add_argument('--phase', required=True, choices=lifecycle.PHASES)
    s.add_argument('--attempts', type=int, default=0)
    s.add_argument('--log', help='the newest boot log written since the phase began')
    s.add_argument('--via-entry', action='store_true', help='this boot started the shim entry')
    s.add_argument('--mok-pending', action='store_true', help='a MOK request is still staged')
    s.set_defaults(fn=cmd_next_step)

    s = sub.add_parser('verify', help='check pinned hashes (local files, or --builds DIR)')
    s.add_argument('--manifest', default=str(root / 'third_party' / 'manifest.json'))
    s.add_argument('--root', default=str(root / 'local'))
    s.add_argument('--builds', metavar='DIR')
    s.add_argument('names', nargs='*', metavar='VARIANT', help='with --builds: only these images')
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser('banner', help='encode the start-screen art for the ESP')
    s.add_argument('out')
    s.add_argument('--art', default=str(root / 'config' / 'banner.txt'))
    s.set_defaults(fn=cmd_banner)

    s = sub.add_parser('bench', help='tensor-core throughput check (needs torch with CUDA)')
    s.add_argument('--size', type=int, default=8192)
    s.add_argument('--iters', type=int, default=50)
    s.add_argument('--rounds', type=int, default=3)
    s.set_defaults(fn=cmd_bench)

    s = sub.add_parser('keep', help='keep the RTX powered (hybrid mode): runs until stopped')
    s.add_argument('--log', required=True, help='file the keeper appends its lines to')
    s.set_defaults(fn=cmd_keep)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        return a.fn(a)
    except (ValueError, KeyError, OSError) as e:
        print(f'kachow {a.command}: {e}', file=sys.stderr)
        return 2
