"""Integration tests: the parts of FirmwareVars.psm1 and Install.psm1 that need no elevation
(boot order arithmetic, picking the newest boot log), run in Windows PowerShell 5.1."""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
WIN = REPO / 'src' / 'windows'
PS = shutil.which('powershell') or shutil.which('pwsh')

pytestmark = pytest.mark.skipif(PS is None, reason='no PowerShell on this machine')


def ps(script):
    r = subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def move(order, number, index):
    out = ps(f"Import-Module '{WIN / 'FirmwareVars.psm1'}'; "
             f"(Move-BootNumber -Order @({','.join(map(str, order))}) -Number {number} -Index {index}) -join ','")
    return [int(x) for x in out.split(',')]


@pytest.mark.parametrize('order, number, index, want', [
    ([2, 1, 0x2001], 2, 0, [2, 1, 0x2001]),     # already first
    ([1, 2, 0x2001], 2, 0, [2, 1, 0x2001]),     # moved to the front
    ([2, 1, 0x2001], 2, 1, [1, 2, 0x2001]),     # straight after Windows Boot Manager
    ([1, 0x2001], 2, 1, [1, 2, 0x2001]),        # inserted when absent
    ([1, 0x2001], 2, 9, [1, 0x2001, 2]),        # clamped to the end
    ([1, 0x2001], 2, -3, [2, 1, 0x2001]),       # and to the front
    ([1, 2, 2], 2, 1, [1, 2]),                  # a duplicate is dropped
])
def test_move_boot_number(order, number, index, want):
    assert move(order, number, index) == want


def test_boot_order_bytes_round_trip():
    out = ps(f"Import-Module '{WIN / 'FirmwareVars.psm1'}'; "
             "$b = ConvertTo-BootOrder @(2, 1, 0x2001); ($b -join ',') + '|' + ((ConvertFrom-BootOrder $b) -join ',')")
    data, numbers = out.split('|')
    assert data == '2,0,1,0,1,32' and numbers == f'2,1,{0x2001}'


def power_state(data):
    return ps(f"Import-Module '{WIN / 'Machine.psm1'}'; ConvertFrom-PowerData ([byte[]]@({','.join(map(str, data))}))")


def test_power_data_most_recent_state():
    # CM_POWER_DATA: PD_Size, then PD_MostRecentPowerState (1 = D0 ... 4 = D3)
    assert [power_state([56, 0, 0, 0, n, 0, 0, 0]) for n in (1, 2, 3, 4)] == ['D0', 'D1', 'D2', 'D3']
    assert power_state([56, 0, 0, 0, 0, 0, 0, 0]) == 'unknown'
    assert power_state([56, 0, 0, 0, 5, 0, 0, 0]) == 'unknown'
    assert power_state([56, 0, 0]) == 'unknown'


def test_newest_boot_log_after_a_number(tmp_path):
    logs = tmp_path / 'esp' / 'GPU4090-UNLOCK'
    logs.mkdir(parents=True)
    for n in (3, 18, 21, 9):
        (logs / f'RUN{n:04d}.TXT').write_text(f'run {n}\n')
    (logs / 'RUNLAST.TXT').write_text('not a run\n')
    into = tmp_path / 'copies'
    out = ps(f"Import-Module '{WIN / 'Install.psm1'}'; "
             f"$a = Get-NewRunLog -Esp '{tmp_path / 'esp'}' -After 18 -Into '{into}'; \"$($a.Number);$($a.Path)\"; '|'; "
             f"$b = Get-NewRunLog -Esp '{tmp_path / 'esp'}' -After 21 -Into '{into}'; if ($null -eq $b) {{ 'none' }}; '|'; "
             f"$c = Get-NewRunLog -Esp '{tmp_path / 'nowhere'}' -Into '{into}'; if ($null -eq $c) {{ 'none' }}")
    first, second, third = [s.strip() for s in out.split('|')]
    assert first == f'21;{into / "RUN0021.TXT"}'
    assert (into / 'RUN0021.TXT').read_text() == 'run 21\n'
    assert second == 'none' and third == 'none'
