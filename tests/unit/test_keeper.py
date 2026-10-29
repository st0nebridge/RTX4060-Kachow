"""Unit tests for kachow.keeper: the CUDA context that keeps the RTX powered (hybrid mode)."""
import pytest

from kachow import cli, keeper


class FakeCuda:
    """The CUDA driver calls keeper makes, recorded; `fail` names one that returns an error."""

    def __init__(self, fail=None, code=100):
        self.calls = []
        self.fail, self.code = fail, code
        for name in keeper.SIGNATURES:
            setattr(self, name, self._make(name))

    def _make(self, name):
        def call(*args):
            self.calls.append((name, args))
            if name == 'cuDeviceGetName':
                args[0].value = b'Fake RTX'
            return self.code if name == self.fail else 0
        return call

    def names(self):
        return [n for n, _ in self.calls]


def run(cu, rounds, period=1.0):
    lines, sleeps = [], []
    n = keeper.hold(cu, lines.append, period=period, sleep=sleeps.append, stop=lambda i: i >= rounds)
    return n, lines, sleeps


def test_holds_a_context_and_touches_it_every_period():
    cu = FakeCuda()
    n, lines, sleeps = run(cu, 3, period=0.5)
    assert n == 3
    assert cu.names()[:5] == ['cuInit', 'cuDeviceGet', 'cuDeviceGetName', 'cuCtxCreate_v2', 'cuMemAlloc_v2']
    assert cu.names()[5:] == ['cuMemsetD8_v2', 'cuCtxSynchronize'] * 3
    assert sleeps == [0.5, 0.5]                      # no sleep after the last round
    assert lines[0].startswith('holding Fake RTX (context up in ')


def test_the_context_is_on_device_zero_with_the_full_name():
    cu = FakeCuda()
    run(cu, 1)
    calls = dict(cu.calls)
    assert calls['cuInit'] == (0,)
    assert calls['cuDeviceGet'][1] == 0
    buf, length, _ = calls['cuDeviceGetName']
    assert length == len(buf) == 128


def test_the_time_to_hold_is_measured_from_the_start():
    ticks = iter([1.0, 3.5])
    lines = []
    keeper.hold(FakeCuda(), lines.append, sleep=lambda s: None, stop=lambda i: True, clock=lambda: next(ticks))
    assert lines[0] == 'holding Fake RTX (context up in 2.50 s)'


def test_memory_written_is_the_allocation_and_changes_each_round():
    cu = FakeCuda()
    run(cu, 3)
    alloc = next(a for n, a in cu.calls if n == 'cuMemAlloc_v2')
    assert alloc[1] == keeper.SIZE == 1 << 20
    sets = [a for n, a in cu.calls if n == 'cuMemsetD8_v2']
    assert [s[1] for s in sets] == [0, 1, 2] and all(s[2] == keeper.SIZE for s in sets)
    assert [n for n, a in cu.calls if n == 'cuCtxCreate_v2' and a[1] == 0] == ['cuCtxCreate_v2']


def test_value_wraps_at_a_byte():
    cu = FakeCuda()
    run(cu, 257, period=0)
    sets = [a[1] for n, a in cu.calls if n == 'cuMemsetD8_v2']
    assert sets[255] == 255 and sets[256] == 0


def test_says_alive_after_a_minute_then_hourly():
    _, lines, _ = run(FakeCuda(), 7201, period=0)
    assert [ln for ln in lines if ln.startswith('alive')] == ['alive 60 s', 'alive 3600 s', 'alive 7200 s']


@pytest.mark.parametrize('name', list(keeper.SIGNATURES))
def test_a_failed_call_raises_with_its_name(name):
    with pytest.raises(keeper.KeeperError, match=rf'^{name} failed: CUresult 100$'):
        run(FakeCuda(fail=name), 2)


def test_bind_sets_every_signature():
    cu = FakeCuda()
    assert keeper.bind(cu) is cu
    for name, sig in keeper.SIGNATURES.items():
        assert getattr(cu, name).argtypes == sig


class Interrupted(Exception):
    pass


def test_by_default_it_holds_until_the_process_is_stopped():
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 5:
            raise Interrupted
    with pytest.raises(Interrupted):
        keeper.hold(FakeCuda(), lambda m: None, sleep=sleep)
    assert sleeps == [1.0] * 5


def test_keep_command_logs_with_a_time_and_exits_1_on_a_cuda_error(tmp_path, capsys):
    log = tmp_path / 'local' / 'logs' / 'keeper.log'
    a = cli.parser().parse_args(['keep', '--log', str(log)])
    assert cli.cmd_keep(a, load=FakeCuda, stop=lambda i: i >= 2) == 0
    first = log.read_text('utf-8').splitlines()[0]
    assert first[:2].isdigit() and first[2] == ':' and ' holding Fake RTX' in first
    assert cli.cmd_keep(a, load=lambda: FakeCuda(fail='cuInit'), stop=lambda i: True) == 1
    assert log.read_text('utf-8').splitlines()[-1].endswith('cuInit failed: CUresult 100')
    assert 'kachow keep: cuInit failed' in capsys.readouterr().err


def test_keep_requires_a_log():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(['keep'])
