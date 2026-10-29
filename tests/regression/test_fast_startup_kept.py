"""Regression test CU-20261029-001 (Fast Startup and hibernate keep the unlock): every
power-on from off runs the unlocker before Windows resumes (RUN0024/RUN0025 after Fast
Startup shutdowns, boot type 0x1; RUN0026 after hibernate, 0x2; all unlocked, 46.0-46.1
TFLOPS). So install leaves Fast Startup as it is, status no longer calls it a fault, and
uninstall restores only a value an earlier install turned off. Sleep still loses it;
Restart is covered by CU-20261029-005."""
import re
from pathlib import Path

from kachow import lifecycle
from kachow.lifecycle import next_step
from kachow import runlog

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
README = (REPO / 'README.md').read_text('utf-8')


def body(text, name):
    return re.search(rf'function {name}\b.*?\n\}}', text, re.S).group(0)


def test_install_leaves_fast_startup_alone():
    b = body(SCRIPT, 'Invoke-Install')
    assert 'Set-FastStartup' not in b
    assert 'Fast Startup off' not in b and 'Turn Fast Startup' not in b


def test_a_record_from_an_earlier_install_keeps_its_saved_value():
    b = body(SCRIPT, 'Invoke-Install')
    assert "$rec.ContainsKey('fastStartup')" in b and '$new.fastStartup = $rec.fastStartup' in b
    u = body(SCRIPT, 'Invoke-Uninstall')
    assert u.count('Set-FastStartup') == 1
    assert "$null -ne $rec['fastStartup'] -and $rec.fastStartup -ne 0) { Set-FastStartup $rec.fastStartup" in u


def test_status_reports_fast_startup_without_calling_it_a_fault():
    s = body(SCRIPT, 'Show-Status')
    assert 'turn it off' not in s and 'needs a full shutdown' not in s
    assert 'Fast Startup:' in s


def test_the_boot_advice_names_restart_not_fast_startup():
    assert 'Shut down fully' not in SCRIPT
    assert 'not Restart' in body(SCRIPT, 'Invoke-Shutdown')
    warm = next_step('unlock', runlog.parse('build=auto\nSKIP: stage=cold-state status=0x7\n'), 0, True, False)
    assert 'fully' not in warm.message and 'not Restart' in warm.message
    done = next_step('unlock', runlog.parse(
        'build=auto\nChecks passed.\nchoice: unlock\nTRANSACTION OK: x\nPOST-GOP SS0=0x88888888 SS1=0x8\n'), 0, True, False)
    assert 'Hibernate' in done.message and 'Sleep' in done.message
    assert lifecycle.WARM_STAGE == 'cold-state'


def test_the_readme_no_longer_asks_for_fast_startup_off():
    assert 'Fast Startup off' not in README and 'Keep Windows Fast Startup off' not in README
    section = README[README.index('## The unlock needs a power-on'):README.index('## How it works')]
    for word in ('Fast Startup', 'Hibernate', 'Restart', 'Sleep'):
        assert word in section
