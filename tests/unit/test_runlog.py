"""Unit tests for kachow.runlog. Fixtures are the hardware boot logs
RUN0003 (dryrun, excerpt) and RUN0018 (automatic unlock, complete) recorded on 2026-10-28."""
from pathlib import Path

import pytest

from kachow import runlog

FIX = Path(__file__).resolve().parents[1] / 'fixtures'


def load(name):
    return (FIX / name).read_text()


def test_recorded_auto_unlock_parses_as_unlocked():
    log = runlog.parse(load('RUN0018-auto-unlocked.txt'))
    assert log.build == 'auto' and log.choice == 'unlock'
    assert log.post_gop == (0x88888888, 0x8)
    assert log.transaction_ok and not log.stopped
    assert log.status == 'unlocked'
    assert log.last_line == 'Unlocked. Starting Windows.'


def test_recorded_dryrun_parses_as_dryrun():
    log = runlog.parse(load('RUN0003-dryrun.excerpt.txt'))
    assert log.build == 'dryrun' and log.via_shim
    assert log.post_gop == () and not log.transaction_ok
    assert log.status == 'dryrun'


def test_stopped_wins_over_everything():
    text = load('RUN0018-auto-unlocked.txt') + 'display release STOPPED: hold power\n'
    assert runlog.parse(text).status == 'stopped'


@pytest.mark.parametrize('gop', ['POST-GOP SS0=0x2747060 SS1=0x5', 'POST-GOP SS0=0x88888888 SS1=0x5',
                                 'POST-GOP SS0=0x2747060 SS1=0x8', 'POST-GOP SS0=0x88888888 SS1=0x9',
                                 'POST-GOP SS0=0x99999999 SS1=0x8'])
def test_transaction_ok_without_unlocked_selectors_is_not_unlocked(gop):
    text = f'RTX 4060 Laptop unlock build=auto\n{gop}\nTRANSACTION OK: x\n'
    assert runlog.parse(text).status == 'not-unlocked'


def test_selectors_without_transaction_ok_is_not_unlocked():
    text = 'build=manual\nPOST-GOP SS0=0x88888888 SS1=0x8\n'
    assert runlog.parse(text).status == 'not-unlocked'


def test_reltest_counts_as_dryrun():
    assert runlog.parse('unlock build=reltest\n').status == 'dryrun'


def test_empty_log():
    log = runlog.parse('')
    assert (log.build, log.choice, log.post_gop, log.last_line) == ('', '', (), '')
    assert log.status == 'not-unlocked'


def test_summary_line():
    log = runlog.parse(load('RUN0018-auto-unlocked.txt'))
    assert runlog.summary(log) == ('status=unlocked build=auto choice=unlock SS0=0x88888888 SS1=0x8 '
                                   'via_shim=1 last="Unlocked. Starting Windows."')
    assert runlog.summary(runlog.parse('')) == ('status=not-unlocked build=? choice=- no POST-GOP readback '
                                                'via_shim=0 last=""')


def test_selectors_are_read_as_hex():
    # "1F" and "10" read differently in base 15, 16 and 17
    assert runlog.parse('POST-GOP SS0=0x1F SS1=0x10\n').post_gop == (0x1F, 0x10)


def test_a_skipped_run_names_its_check():
    log = runlog.parse('build=auto\nChecks passed.\nSKIP: stage=cold-state status=0x7 fault=0\n')
    assert log.skip_stage == 'cold-state' and log.status == 'skipped'
    assert runlog.summary(log) == ('status=skipped build=auto choice=- no POST-GOP readback skip=cold-state '
                                   'via_shim=0 last="SKIP: stage=cold-state status=0x7 fault=0"')


def test_a_skipped_dryrun_is_not_a_dryrun_pass():
    assert runlog.parse('build=dryrun\nSKIP: stage=assets status=0x1b fault=0\n').status == 'skipped'


def test_an_unlock_outranks_a_skip_line():
    text = load('RUN0018-auto-unlocked.txt') + 'SKIP: stage=x status=0 fault=0\n'
    assert runlog.parse(text).status == 'unlocked'


def test_skip_only_counts_at_the_start_of_a_line():
    assert runlog.parse('note: SKIP: stage=x\n').skip_stage == ''


@pytest.mark.parametrize('text, passed', [
    ('build=dryrun\nChecks passed.\n', True),
    ('build=dryrun\n  Checks passed.  \n', True),
    ('build=dryrun\nChecks passed. not really\n', False),
    ('build=dryrun\n', False),
])
def test_checks_passed_is_its_own_line(text, passed):
    assert runlog.parse(text).checks_passed is passed
