"""Decide the installer's next step from what the last boot left behind.

@module kachow.lifecycle
@description `kachow.ps1 install` spans several boots: a trial boot of the dry-run build,
then the first unlock boot. After each boot it reports the phase, the newest boot log
written since that phase began, whether the boot started the shim entry and whether a MOK
request is still pending; next_step() says what to do. No I/O.
@input str phase, RunLog or None, int attempts, bool via_entry, bool mok_pending
@output Step - the action, the phase to record and the message for the user
@dependencies kachow.runlog (RunLog)

@example
    next_step('trial', runlog.parse(text), 0, via_entry=True, mok_pending=False).action  # 'advance'
"""
from dataclasses import dataclass

MAX_RETRIES = 2              # boots retried before the install gives up: three boots in all
WARM_STAGE = 'cold-state'   # the unlocker's own check that the GPU is fresh from power-on
DECLINED = 'windows'         # choice logged when Esc was pressed at the countdown


@dataclass(frozen=True)
class Step:
    action: str   # retry | advance | finish | stop
    phase: str
    message: str


def next_step(phase, log, attempts, via_entry, mok_pending):
    """The step after a boot in `phase`; `log` is the newest log since the phase began and
    `attempts` the boots of this phase already retried."""
    if phase not in _AFTER:
        raise ValueError(f'no next step from phase {phase!r}')
    if log is None:
        return _retry(phase, attempts, _no_log(via_entry, mok_pending))
    if log.status == 'stopped':
        return Step('stop', 'failed', f'The unlocker stopped the machine: "{log.last_line}". '
                                      'Read the boot log before trying again.')
    if log.status == 'skipped':
        if log.skip_stage == WARM_STAGE:
            return _retry(phase, attempts, 'The unlocker skipped: the GPU was not fresh from power-on. '
                                           'Shut down (not Restart), then power on.')
        return Step('stop', 'failed', f'The unlocker refused at its "{log.skip_stage}" check and started '
                                      'Windows unchanged. Read the boot log before trying again.')
    return _AFTER[phase](log, attempts)


def _after_trial(log, attempts):
    if log.status == 'dryrun' and log.checks_passed and log.via_shim:
        return Step('advance', 'unlock', 'The trial boot passed every check through shim. '
                                         'The next boot unlocks.')
    return Step('stop', 'failed', f'The trial boot did not pass its checks ({log.status}).')


def _after_unlock(log, attempts):
    if log.status == 'unlocked':
        return Step('finish', 'installed', 'Unlocked. From now on every Shut down, Restart or '
                                           'Hibernate unlocks; Sleep does not.')
    if log.choice == DECLINED:
        return _retry('unlock', attempts, 'Esc was pressed at the countdown, so Windows started '
                                          'without the unlock. Let the countdown run out next time.')
    return Step('stop', 'failed', f'The unlock boot did not unlock ({log.status}).')


_AFTER = {'trial': _after_trial, 'unlock': _after_unlock}
PHASES = tuple(_AFTER)


def _no_log(via_entry, mok_pending):
    if mok_pending:
        return ('Shim did not run: the firmware ignored the one-time boot request. If it '
                'happens again, choose "Tensor Unlock (shim)" in the firmware boot menu.')
    if via_entry:
        return ('Shim ran but did not start the unlocker: it refused the image (Security '
                'Violation), so the key is not enrolled. The request is staged again.')
    return ('The unlocker did not run. If MokManager\'s blue screen appeared, it restarts into '
            'Windows after enrolling the key; that is expected. Shut down and power on again.')


def _retry(phase, attempts, message):
    if attempts >= MAX_RETRIES:
        return Step('stop', 'failed', f'{message} Gave up after {MAX_RETRIES} retries.')
    return Step('retry', phase, message)
