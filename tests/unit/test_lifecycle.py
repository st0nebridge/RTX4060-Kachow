"""Unit tests for kachow.lifecycle: the installer's next step after each boot."""
from dataclasses import dataclass

import pytest

from kachow import lifecycle, runlog
from kachow.lifecycle import next_step

DRYRUN_OK = ('RTX 4060 Laptop unlock build=dryrun\nSecure Boot on: started through shim (MOK-verified image)\n'
             'Checks passed.\nDRY RUN build: no display release and no GPU write. Starting Windows.\n')
UNLOCKED = ('RTX 4060 Laptop unlock build=auto\nSecure Boot on: started through shim (MOK-verified image)\n'
            'Checks passed.\nchoice: unlock\nTRANSACTION OK: x\nPOST-GOP SS0=0x88888888 SS1=0x8\n'
            'Unlocked. Starting Windows.\n')


def log(text):
    return runlog.parse(text)


def step(phase, text=None, attempts=0, via_entry=True, mok_pending=False):
    return next_step(phase, log(text) if text is not None else None, attempts, via_entry, mok_pending)


def test_a_clean_trial_advances_to_the_unlock():
    s = step('trial', DRYRUN_OK)
    assert (s.action, s.phase) == ('advance', 'unlock')


@pytest.mark.parametrize('text', [
    DRYRUN_OK.replace('Checks passed.\n', ''),                          # the checks did not all run
    DRYRUN_OK.replace('started through shim', 'started'),               # not through shim
    DRYRUN_OK.replace('build=dryrun', 'build=auto'),                    # the wrong image was installed
])
def test_a_trial_that_proves_less_stops(text):
    s = step('trial', text)
    assert (s.action, s.phase) == ('stop', 'failed')


def test_an_unlocked_boot_finishes():
    s = step('unlock', UNLOCKED)
    assert (s.action, s.phase) == ('finish', 'installed')


def test_an_unlocked_log_in_the_trial_phase_is_not_a_pass():
    assert step('trial', UNLOCKED).action == 'stop'


@pytest.mark.parametrize('phase', ['trial', 'unlock'])
def test_stopped_always_stops(phase):
    s = step(phase, UNLOCKED + 'STOPPED. Power OFF with the power button.\n')
    assert (s.action, s.phase) == ('stop', 'failed') and 'STOPPED' in s.message


@pytest.mark.parametrize('phase', ['trial', 'unlock'])
def test_a_warm_gpu_is_retried_with_a_shutdown_not_a_restart(phase):
    s = step(phase, 'build=auto\nSKIP: stage=cold-state status=0x7 fault=0\n')
    assert (s.action, s.phase) == ('retry', phase) and 'Shut down (not Restart)' in s.message


def test_any_other_skip_stops_and_names_the_check():
    s = step('unlock', 'build=auto\nSKIP: stage=display-preflight status=0x3 fault=0\n')
    assert (s.action, s.phase) == ('stop', 'failed') and '"display-preflight"' in s.message


def test_esc_at_the_countdown_is_retried():
    s = step('unlock', 'build=auto\nChecks passed.\nchoice: windows without the mod\n')
    assert (s.action, s.phase) == ('retry', 'unlock') and 'Esc' in s.message


def test_an_unlock_boot_that_did_not_unlock_stops():
    s = step('unlock', 'build=auto\nChecks passed.\nchoice: unlock\n')
    assert (s.action, s.phase) == ('stop', 'failed') and 'not-unlocked' in s.message


@pytest.mark.parametrize('via_entry, mok_pending, words', [
    (False, True, 'ignored the one-time boot'),
    (True, True, 'ignored the one-time boot'),     # a pending request means shim never got to it
    (True, False, 'Security Violation'),
    (False, False, 'MokManager'),
])
def test_no_log_says_why(via_entry, mok_pending, words):
    s = step('trial', None, via_entry=via_entry, mok_pending=mok_pending)
    assert (s.action, s.phase) == ('retry', 'trial') and words in s.message


@pytest.mark.parametrize('attempts, action', [(0, 'retry'), (1, 'retry'), (2, 'stop'), (5, 'stop')])
def test_retries_give_up_after_two_retries(attempts, action):
    s = step('unlock', None, attempts=attempts)
    assert s.action == action
    if action == 'stop':
        assert s.phase == 'failed' and 'Gave up after 2 retries' in s.message
    assert lifecycle.MAX_RETRIES == 2


@pytest.mark.parametrize('phase', ['installed', 'failed', '', 'TRIAL'])
def test_only_the_two_boot_phases_have_a_next_step(phase):
    with pytest.raises(ValueError, match='no next step'):
        step(phase, DRYRUN_OK)
    assert lifecycle.PHASES == ('trial', 'unlock')


@dataclass(frozen=True)
class FakeLog:
    """A log as JSON or argv would hand it over: strings built at run time, so an identity
    check cannot pass for an equality check."""
    status: str
    choice: str = ''
    checks_passed: bool = True
    via_shim: bool = True
    skip_stage: str = ''
    last_line: str = ''


def fresh(s):
    return ''.join(list(s))


@pytest.mark.parametrize('phase, status, choice, action', [
    (fresh('trial'), fresh('dryrun'), '', 'advance'),
    (fresh('unlock'), fresh('unlocked'), '', 'finish'),
    (fresh('unlock'), fresh('not-unlocked'), fresh('windows'), 'retry'),
    (fresh('trial'), fresh('stopped'), '', 'stop'),
])
def test_values_built_at_run_time_decide_the_same(phase, status, choice, action):
    assert next_step(phase, FakeLog(status, choice), 0, True, False).action == action


@pytest.mark.parametrize('phase, log', [
    ('trial', FakeLog('aborted')),                   # sorts before "dryrun"
    ('unlock', FakeLog('verified')),                 # sorts after "unlocked"
    ('unlock', FakeLog('not-unlocked', 'yes')),      # a choice that sorts after "windows"
    ('unlock', FakeLog('skipped', skip_stage='assets')),   # a check that sorts before "cold-state"
])
def test_anything_unrecognised_stops(phase, log):
    assert next_step(phase, log, 0, True, False).action == 'stop'


@pytest.mark.parametrize('phase', ['trial', 'unlock'])
def test_a_fresh_stopped_status_quotes_the_stop_line(phase):
    log = FakeLog(fresh('stopped'), last_line=fresh('STOP: stage=display-release'))
    s = next_step(phase, log, 0, True, False)
    assert s.action == 'stop' and 'stopped the machine' in s.message and 'STOP: stage=display-release' in s.message


def test_a_fresh_warm_stage_is_still_retried():
    log = FakeLog(fresh('skipped'), skip_stage=fresh('cold-state'))
    assert next_step('unlock', log, 0, True, False).action == 'retry'
