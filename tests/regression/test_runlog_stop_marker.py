"""Regression test CU-20261028-013: runlog took "STOPPED" as the stop marker, but that is
the console's wording; the unlocker's log says "STOP: stage=..." (upstream app.c), so a
failed unlock read as not-unlocked, or as a dry-run pass for a dry-run build."""
from kachow import lifecycle, runlog

STOP = ('RTX 4060 Laptop unlock build=dryrun\nChecks passed.\n'
        'STOP: stage=final-verification status=0x6 released=1 started=0 mmio_writes=0 retained=0 fault=0\n'
        'Display restored. Starting Windows without the mod.\n')


def test_the_logged_stop_line_reads_as_stopped():
    assert runlog.parse(STOP).status == 'stopped'
    assert runlog.parse(STOP.replace('build=dryrun', 'build=auto')).status == 'stopped'


def test_a_stopped_trial_never_advances_the_install():
    step = lifecycle.next_step('trial', runlog.parse(STOP), 0, True, False)
    assert step.action == 'stop'


def test_stop_must_start_the_line():
    assert runlog.parse('build=auto\nnote STOP: later\n').status == 'not-unlocked'
