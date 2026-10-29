"""Regression test CU-20261029-005 (Restart keeps the unlock): with the automatic build,
the last four restarts in a row unlocked (RUN0022 and RUN0023 from the Start menu, RUN0027
from a NitroSense mode switch, RUN0030 from `shutdown /r`); the one failure, RUN0019 on
2026-10-28, was the first restart on that build and its log ends after the GPU reset.
RUN0016 (STOP) ran the manual build, which stopped after a Shut down too (RUN0015), so it
does not count against Restart. Sleep still loses the unlock: waking from S3 does not run
the firmware boot. The warm-GPU retry keeps its Shut down advice."""
import re
from pathlib import Path

import pytest

from kachow import runlog
from kachow.lifecycle import next_step

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
README = (REPO / 'README.md').read_text('utf-8')
DECISIONS_MD = REPO / 'DECISIONS.md'
# the decision record stays in the development repository; a release tree has none
needs_decisions = pytest.mark.skipif(not DECISIONS_MD.exists(), reason='no DECISIONS.md in this tree')
UNLOCKED = 'build=auto\nChecks passed.\nchoice: unlock\nTRANSACTION OK: x\nPOST-GOP SS0=0x88888888 SS1=0x8\n'


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_the_finish_message_counts_restart_in_and_sleep_out():
    done = next_step('unlock', runlog.parse(UNLOCKED), 0, True, False)
    assert done.action == 'finish'
    assert 'Restart' in done.message and 'Restart and Sleep do not' not in done.message
    assert 'Sleep does not' in done.message


def test_status_counts_restart_in_and_sleep_out():
    s = body(SCRIPT, 'Show-Status')
    assert 'Restart and Sleep do not' not in s
    assert 'Shut down, Restart or Hibernate' in s and 'Sleep does not' in s


def test_the_warm_gpu_retry_still_asks_for_a_shut_down():
    warm = next_step('unlock', runlog.parse('build=auto\nSKIP: stage=cold-state status=0x7\n'), 0, True, False)
    assert 'Shut down (not Restart)' in warm.message


def test_the_readme_gives_the_restart_record():
    section = README[README.index('## The unlock needs a power-on'):README.index('## How it works')]
    assert 'Restart, Sleep' not in section and 'not a reliable way back' not in section
    for run in ('RUN0019', 'RUN0022', 'RUN0023', 'RUN0027', 'RUN0030', 'RUN0016', 'RUN0015'):
        assert run in section
    limits = README[README.index('## Limits'):README.index('## Recovery')]
    assert 'not Restart or Sleep' not in limits and 'Sleep' in limits


@needs_decisions
def test_the_decision_supersedes_the_restart_part_only():
    decisions = DECISIONS_MD.read_text('utf-8')
    assert '[D-20261029-004]' in decisions
    assert 'Restart part superseded by D-20261029-004' in decisions
