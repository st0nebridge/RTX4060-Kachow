#Requires -Version 5.1
<#
.SYNOPSIS
  Mutation pass over src/kachow with cosmic-ray, sandboxed.
.DESCRIPTION
  cosmic-ray rewrites source files in place while it runs: do not edit or test src/ until
  it finishes. HOME, USERPROFILE, APPDATA, LOCALAPPDATA and XDG_CONFIG_HOME point into
  local\mutation-sandbox (emptied first), so a mutant that drops an explicit path cannot
  reach the real profile. Results: local\cosmic-ray.sqlite; the report prints at the end.
  -Modules mutates only those files (paths under src/kachow) into
  local\cosmic-ray-modules.sqlite: for a change to a few modules after a full pass.
.EXAMPLE
  .\bin\mutate.ps1
  .\bin\mutate.ps1 -ReportOnly
  .\bin\mutate.ps1 -Modules src/kachow/lifecycle.py, src/kachow/runlog.py
#>
[CmdletBinding()]
param([switch]$ReportOnly, [string[]]$Modules)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot
$cr = Join-Path $root '.venv\Scripts'
$db = Join-Path $root 'local\cosmic-ray.sqlite'
$cfg = Join-Path $root 'cosmic-ray.toml'
if ($Modules) {
    foreach ($m in $Modules) { if (-not (Test-Path (Join-Path $root $m))) { throw "No module $m" } }
    $db = Join-Path $root 'local\cosmic-ray-modules.sqlite'
    $list = ($Modules | ForEach-Object { '"' + ($_ -replace '\\', '/') + '"' }) -join ', '
    $text = (Get-Content $cfg -Raw) -replace '(?m)^module-path = .*$', "module-path = [$list]"
    $cfg = Join-Path $root 'local\cosmic-ray-modules.toml'
    Set-Content $cfg $text -Encoding ascii
}

Push-Location $root
try {
    if (-not $ReportOnly) {
        $sandbox = Join-Path $root 'local\mutation-sandbox'
        if (Test-Path $sandbox) { Remove-Item $sandbox -Recurse -Force }
        foreach ($d in 'home', 'appdata', 'localappdata', 'config') { New-Item -ItemType Directory -Force (Join-Path $sandbox $d) | Out-Null }
        $env:HOME = Join-Path $sandbox 'home'
        $env:USERPROFILE = Join-Path $sandbox 'home'
        $env:APPDATA = Join-Path $sandbox 'appdata'
        $env:LOCALAPPDATA = Join-Path $sandbox 'localappdata'
        $env:XDG_CONFIG_HOME = Join-Path $sandbox 'config'
        $env:PATH = "$cr;$env:PATH"   # the config's `python` must be the project venv
        # cosmic-ray decodes test output as UTF-8; a cp1252 pipe (pytest.approx prints a
        # plus-minus sign) makes it crash and file a killed mutant as INCOMPETENT
        $env:PYTHONUTF8 = '1'
        $srcHash = { (Get-ChildItem (Join-Path $root 'src') -Recurse -File -Filter *.py | Sort-Object FullName | Get-FileHash -Algorithm SHA256 | ForEach-Object { $_.Hash }) -join ',' }
        $before = & $srcHash

        # The filter must select tests and the unmutated run must be green;
        # cosmic-ray's own baseline also passes when the command cannot start at all.
        $collected = & python -m pytest --collect-only -q -p no:cacheprovider tests/unit tests/regression -k 'not original_powershell'
        # pyproject adds -q, so this is -qq: one "path.py: N" line per file, no summary line
        $n = 0
        foreach ($line in $collected) { if ($line -match '\.py: (\d+)$') { $n += [int]$Matches[1] } }
        if ($n -eq 0) { $n = [int](([regex]::Match(($collected -join ' '), '(\d+)(?:/\d+)? tests? (?:collected|selected)')).Groups[1].Value) }
        if ($n -lt 1) { throw "mutation test filter selects no tests: $($collected | Select-Object -Last 1)" }
        & python -m pytest -x -q -p no:cacheprovider tests/unit tests/regression -k 'not original_powershell'
        if ($LASTEXITCODE) { throw 'unmutated baseline failed: fix the suite before mutating' }
        Write-Host "Baseline green with $n tests"

        if (Test-Path $db) { Remove-Item $db -Force }
        & (Join-Path $cr 'cosmic-ray.exe') init $cfg $db
        & (Join-Path $cr 'cr-filter-pragma.exe') $db   # skip lines marked `# pragma: no mutate` (each says why)
        if ($LASTEXITCODE) { throw 'cr-filter-pragma failed' }
        & (Join-Path $cr 'cosmic-ray.exe') exec $cfg $db
        if ($LASTEXITCODE) { throw 'cosmic-ray exec failed' }
        # compare with the tree as it was before the run, so uncommitted work does not trip it
        if ((& $srcHash) -ne $before) { throw 'src/ changed during the run: a mutant was not restored' }
    }
    $counts = & (Join-Path $cr 'python.exe') -c "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(dict(c.execute('select test_outcome, count(*) from work_results group by 1').fetchall()))" $db
    Write-Host "Outcomes: $counts"
    & (Join-Path $cr 'cr-report.exe') $db --show-pending | Select-Object -Last 12
    if ($counts -match 'incompetent') { throw 'some mutants were INCOMPETENT (the test command did not run): the score is not valid' }
} finally { Pop-Location }
