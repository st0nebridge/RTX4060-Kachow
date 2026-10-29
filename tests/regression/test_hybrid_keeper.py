"""Regression test CU-20261029-002 (hybrid mode through the keeper): in hybrid (Optimus)
mode the driver powers the idle RTX off and the power-off resets the unlock; a process that
keeps using the RTX stops that (2026-10-29: RUN0027/RUN0028 unlocked, GEMM UNLOCKED 47.5 and
47.3 TFLOPS while the keeper held it; D3 within 1 s of stopping it, then LOCKED 30.2). The
keeper runs as SYSTEM from startup, logs the RTX power state before it takes hold, and is
added at the first unlock and at adopt, kept by the guard, and removed by every way out."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
KEEPER = (REPO / 'bin' / 'keeper.ps1').read_text('utf-8')
MACHINE = (REPO / 'src' / 'windows' / 'Machine.psm1').read_text('utf-8')
README = (REPO / 'README.md').read_text('utf-8')
DECISIONS_MD = REPO / 'DECISIONS.md'
# the decision record stays in the development repository; a release tree has none
needs_decisions = pytest.mark.skipif(not DECISIONS_MD.exists(), reason='no DECISIONS.md in this tree')


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_the_keeper_task_runs_as_system_from_startup_without_a_time_limit():
    b = body(MACHINE, 'Register-KeeperTask')
    assert "New-ScheduledTaskTrigger -AtStartup" in b
    assert "-UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest" in b
    assert '-ExecutionTimeLimit ([TimeSpan]::Zero)' in b and '-RestartCount' in b
    assert '-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries' in b
    assert "bin\\keeper.ps1" in b and '-Python' in b
    assert 'Start-ScheduledTask -TaskName $script:KeeperName' in b


def test_the_keeper_logs_the_rtx_state_before_it_takes_hold():
    assert KEEPER.index('Get-RtxPowerState') < KEEPER.index("'keep', '--log'")
    assert 'boot=' in KEEPER and 'RTX=' in KEEPER


def test_the_keeper_goes_in_at_the_first_unlock_and_at_adopt():
    resume = body(SCRIPT, 'Invoke-Resume')
    finish = resume[resume.index("'finish' {"):resume.index("'stop' {")]
    assert 'Register-KeeperTask' in finish
    assert 'Register-KeeperTask' in body(SCRIPT, 'Invoke-Adopt')
    install = body(SCRIPT, 'Invoke-Install')
    installed = install.index("$rec['phase'] -eq 'installed'")
    # not before a boot has unlocked: only the already-installed path re-registers it
    assert install.count('Register-KeeperTask') == 1 and install.index('Register-KeeperTask') > installed
    assert install.index('Register-KeeperTask') < install.index("'Already installed.")


def test_every_way_out_removes_the_keeper():
    resume = body(SCRIPT, 'Invoke-Resume')
    assert 'Unregister-KeeperTask' in resume[resume.index("'stop' {"):]
    assert 'Unregister-KeeperTask' in body(SCRIPT, 'Invoke-Recover')
    assert 'Unregister-KeeperTask' in body(SCRIPT, 'Invoke-Uninstall')


def test_the_guard_keeps_the_keeper_and_notes_a_lost_race():
    g = body(SCRIPT, 'Invoke-Guard')
    assert 'Get-KeeperTask' in g and 'Register-KeeperTask' in g
    assert "'D3'" in g and 'before the keeper' in g


def test_a_d3_at_keeper_start_is_reported_as_possible_not_certain():
    # RUN0029: RTX=D3 when the keeper started at 130 s, yet GEMM read UNLOCKED (45.1 TFLOPS)
    for text in (body(SCRIPT, 'Invoke-Guard'), body(SCRIPT, 'Show-Status'), KEEPER, README):
        assert 'stock rate' not in text
    assert 'may have been reset' in body(SCRIPT, 'Invoke-Guard') and 'bench.ps1' in body(SCRIPT, 'Invoke-Guard')
    assert 'may have been reset' in body(SCRIPT, 'Show-Status')
    assert 'RUN0029' in README


def test_hybrid_mode_is_no_longer_refused():
    pre = body(SCRIPT, 'Assert-Preflight')
    assert 'Install anyway?' not in pre and 'keeper' in pre
    s = body(SCRIPT, 'Show-Status')
    assert 'Test-HybridGraphics' in s and 'Get-KeeperTask' in s


@needs_decisions
def test_the_decision_record_says_hybrid_works_with_the_keeper():
    decisions = DECISIONS_MD.read_text('utf-8')
    assert '(status: superseded by D-20261029-002)' in decisions
    assert '[D-20261029-002]' in decisions


def test_docs_say_hybrid_works_with_the_keeper():
    assert 'hybrid' in README.lower() and 'keeper' in README.lower()
    assert 'Use BIOS discrete-GPU mode' not in README
