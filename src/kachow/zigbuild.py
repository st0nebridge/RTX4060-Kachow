"""Compile the NekoMirra unlocker EFI variants with zig, using upstream's exact flags.

@module kachow.zigbuild
@description Mirror upstream build.py's compiler and linker invocations without executing
any repository code; unpatched, the output reproduces upstream's prebuilt images byte
for byte.
@input Path repo (patched upstream source), str zig executable, Path out, variant names
@output list[Built] - one image per variant with its size and SHA-256
@dependencies hashlib, subprocess, pathlib (stdlib)

@example
    build(Path("local/build/src"), "zig.exe", Path("local/build"), ["UNLOCK4090"])
"""
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

SOURCES = ('app', 'boot_io', 'release', 'port', 'compat', 'checks', 'profile', 'sha256', 'runtime', 'format',
           'vendor/unlock_610', 'vendor/prep_610', 'vendor/layout_610', 'vendor/vbios_610', 'vendor/gfw_eval')
COMMON = ('-target', 'x86_64-uefi', '-std=c11', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
          '-mno-red-zone', '-fshort-wchar', '-Os', '-g0', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
          '-Wno-misleading-indentation', '-D__KERNEL__', '-DGU_UEFI_PORT', '-DGU_ENTRY_LATCHED_SS1_FULL',
          '-Icompat', '-Ivendor/edk2/Include', '-Ivendor/edk2/Include/X64')
VARIANTS = {'UNLOCK4090': ('auto', ('-DGU_AD104_TRANSACTION',)),
            'UNLOCK4090M': ('manual', ('-DGU_AD104_TRANSACTION', '-DGU_MANUAL')),
            'DRYRUN4090': ('dryrun', ('-DGU_4090_DRYRUN',)),
            'RELTEST4090': ('reltest', ('-DGU_4090_DRYRUN', '-DGU_4090_RELCHECK'))}


@dataclass(frozen=True)
class Built:
    path: Path
    size: int
    sha256: str


def variant_for(build_id):
    """Map a build id (auto, manual, dryrun, reltest) to its variant name."""
    for name, (ident, _defines) in VARIANTS.items():
        if ident == build_id:
            return name
    raise KeyError(f"unknown build id {build_id!r}; expected one of "
                   f"{', '.join(v[0] for v in VARIANTS.values())}")


def object_path(out, name, source):
    return Path(out) / 'obj' / f'{name}-{source.replace("/", "_")}.o'


def compile_command(zig, name, source, out):
    ident, defines = VARIANTS[name]
    return [zig, 'cc', *COMMON, *defines, f'-DGU_BUILD_ID="{ident}"', '-c', f'{source}.c',
            '-o', str(object_path(out, name, source))]


def link_command(zig, name, out):
    objs = [str(object_path(out, name, s)) for s in SOURCES]
    return [zig, 'cc', '-target', 'x86_64-uefi', '-nostdlib', '-s', '-Wl,/Brepro', *objs,
            '-o', str(Path(out) / f'{name}.EFI')]


def build(repo, zig, out, names=None, run=subprocess.run):
    repo, out = Path(repo).resolve(), Path(out).resolve()
    names = list(names or VARIANTS)
    for name in names:
        if name not in VARIANTS:
            raise KeyError(f"unknown variant {name!r}")
    (out / 'obj').mkdir(parents=True, exist_ok=True)
    built = []
    for name in names:
        for s in SOURCES:
            run(compile_command(zig, name, s, out), check=True, cwd=repo)
        run(link_command(zig, name, out), check=True, cwd=repo)
        for extra in (out / f'{name}.pdb', out / f'{name}.lib'):
            extra.unlink(missing_ok=True)
        efi = out / f'{name}.EFI'
        data = efi.read_bytes()
        built.append(Built(efi, len(data), hashlib.sha256(data).hexdigest()))
    return built
