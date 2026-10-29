"""Regression test CU-20261029-006 (public release as RTX4060 Ka-chow!): the tree carries a
licence and package metadata for strangers, the docs use the full model number, the test
gate no longer reads a lint script from the user profile (its lint script is now optional, by
-Preflight or KACHOW_PS_PREFLIGHT), and the installed folder and task names keep the first
name so existing installs carry on."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
README = (REPO / 'README.md').read_text('utf-8')
TEST_GATE = (REPO / 'bin' / 'test.ps1').read_text('utf-8')
PYPROJECT = (REPO / 'pyproject.toml').read_text('utf-8')
MACHINE = (REPO / 'src' / 'windows' / 'Machine.psm1').read_text('utf-8')
RUNTIME = (REPO / 'src' / 'windows' / 'Runtime.psm1').read_text('utf-8')


def test_the_tree_carries_its_licence_and_metadata():
    assert (REPO / 'LICENSE').read_text('utf-8').lstrip().startswith('GNU GENERAL PUBLIC LICENSE')
    assert 'license = "GPL-2.0-only"' in PYPROJECT
    assert 'https://github.com/st0nebridge/RTX4060-Kachow' in PYPROJECT
    assert '[LICENSE](LICENSE)' in README


def test_the_docs_use_the_full_model_number():
    assert README.startswith('# RTX4060 Ka-chow!\n')
    assert 'git clone https://github.com/st0nebridge/RTX4060-Kachow.git' in README
    assert '## Before you start' in README


def test_the_test_gate_takes_its_lint_script_as_a_parameter():
    assert 'USERPROFILE' not in TEST_GATE and 'skills' not in TEST_GATE
    assert '[string]$Preflight = $env:KACHOW_PS_PREFLIGHT' in TEST_GATE
    assert 'if ($Preflight -and (Test-Path $Preflight))' in TEST_GATE


def test_installed_names_keep_the_first_name():
    assert "$script:TaskName = 'RTX40 Ka-chow!'" in MACHINE
    assert "$script:KeeperName = 'RTX40 Ka-chow! keeper'" in MACHINE
    assert "Join-Path $env:ProgramFiles 'RTX40 Ka-chow!'" in RUNTIME
    assert 'keep the\nproject\'s first name' in README
