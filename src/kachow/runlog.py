"""Read the unlocker's boot log (\\GPU4090-UNLOCK\\RUNnnnn.TXT on the ESP).

@module kachow.runlog
@description Extract the facts that say whether a boot unlocked the GPU: build id, menu
choice, final selector readback, TRANSACTION OK, whether every preflight check passed,
the check a skipped run stopped at, and the stop marker.
@input str - the log text
@output RunLog - parsed facts plus a one-word status
@dependencies re (stdlib)

@example
    parse(open("RUN0018.TXT").read()).status   # 'unlocked'
"""
import re
from dataclasses import dataclass

UNLOCKED_SS0 = 0x88888888
UNLOCKED_SS1 = 0x8
DRYRUN_BUILDS = ('dryrun', 'reltest')

_BUILD = re.compile(r'\bbuild=(\w+)')
_CHOICE = re.compile(r'^choice:\s*(\S+)', re.M)
_POST_GOP = re.compile(r'^POST-GOP SS0=0x([0-9a-fA-F]+) SS1=0x([0-9a-fA-F]+)', re.M)
_SKIP = re.compile(r'^SKIP: stage=(\S+)', re.M)


@dataclass(frozen=True)
class RunLog:
    build: str
    choice: str
    post_gop: tuple
    transaction_ok: bool
    stopped: bool
    via_shim: bool
    checks_passed: bool
    skip_stage: str
    last_line: str

    @property
    def status(self):
        if self.stopped:
            return 'stopped'
        if self.transaction_ok and self.post_gop == (UNLOCKED_SS0, UNLOCKED_SS1):
            return 'unlocked'
        if self.skip_stage:
            return 'skipped'
        if self.build in DRYRUN_BUILDS:
            return 'dryrun'
        return 'not-unlocked'


def parse(text):
    build = _BUILD.search(text)
    choice = _CHOICE.search(text)
    gop = _POST_GOP.search(text)
    skip = _SKIP.search(text)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return RunLog(
        build=build.group(1) if build else '',
        choice=choice.group(1) if choice else '',
        post_gop=(int(gop.group(1), 16), int(gop.group(2), 16)) if gop else (),
        transaction_ok=any(ln.startswith('TRANSACTION OK') for ln in lines),
        # the log says "STOP: stage=..."; "STOPPED" is the console's wording
        stopped=any(ln.startswith('STOP:') or 'STOPPED' in ln for ln in lines),
        via_shim='started through shim' in text,
        checks_passed='Checks passed.' in lines,
        skip_stage=skip.group(1) if skip else '',
        last_line=lines[-1] if lines else '',
    )


def summary(log):
    gop = ' '.join(f'{k}=0x{v:x}' for k, v in zip(('SS0', 'SS1'), log.post_gop)) or 'no POST-GOP readback'
    skip = f' skip={log.skip_stage}' if log.skip_stage else ''
    return (f'status={log.status} build={log.build or "?"} choice={log.choice or "-"} '
            f'{gop}{skip} via_shim={int(log.via_shim)} last="{log.last_line}"')
