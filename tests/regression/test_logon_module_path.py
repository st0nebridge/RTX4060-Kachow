"""Regression test CU-20261029-007 (module path of the elevated scripts): the logon task runs
bin\\kachow.ps1 elevated at every logon, and Windows PowerShell 5.1 autoloads modules from
the user's Documents\\WindowsPowerShell\\Modules first, so a module planted there under the
same name as Storage or ScheduledTasks would run elevated with no prompt (public-release
review, 2026-10-29). kachow.ps1 now limits $env:PSModulePath to the two admin-only module
folders before it calls any cmdlet, and every module it needs is found there."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (REPO / 'bin' / 'kachow.ps1').read_text('utf-8')
SYSTEM_PATH = ("$env:PSModulePath = (Join-Path $env:SystemRoot 'system32\\WindowsPowerShell\\v1.0\\Modules') + ';' + "
               "(Join-Path $env:ProgramFiles 'WindowsPowerShell\\Modules')")


def test_kachow_limits_the_module_path_before_any_cmdlet():
    assert SYSTEM_PATH in SCRIPT
    head = SCRIPT[:SCRIPT.index(SYSTEM_PATH)]
    body = head[head.index('$ErrorActionPreference'):]
    # nothing between the param block and the reset may autoload a module
    assert not re.search(r'\b[A-Z][a-z]+-[A-Z]\w+', body.replace('$ErrorActionPreference', ''))


@pytest.mark.skipif(shutil.which('powershell') is None, reason='no Windows PowerShell')
def test_every_module_kachow_needs_is_on_the_system_path():
    probe = SYSTEM_PATH + "; foreach ($m in 'Storage', 'ScheduledTasks', 'BitLocker', 'PnpDevice', 'CimCmdlets') " \
            "{ if (-not (Get-Module -ListAvailable $m)) { Write-Output \"missing $m\" } }"
    r = subprocess.run(['powershell', '-NoProfile', '-Command', probe], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and 'missing' not in r.stdout, r.stdout + r.stderr
