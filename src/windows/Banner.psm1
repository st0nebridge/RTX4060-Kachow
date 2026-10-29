<#
@module Banner
@description Put the start-screen art (config/banner.txt) on a mounted ESP as the
unlocker's \GPU4090-ASSETS\banner.txt and banner-ascii.txt; no art file removes them.
@output Install-EspBanner
@dependencies Project.psm1 (Invoke-Kachow, Get-ProjectRoot, Get-LocalPath)
#>
Set-StrictMode -Version 3
Import-Module (Join-Path $PSScriptRoot 'Project.psm1')

$script:Files = @('banner.txt', 'banner-ascii.txt')

# Encodes -Art (default config\banner.txt) and copies both files to $Esp\GPU4090-ASSETS\.
function Install-EspBanner {
    param([Parameter(Mandatory)] [string]$Esp, [string]$Art = (Join-Path (Get-ProjectRoot) 'config\banner.txt'))
    $dir = Join-Path $Esp 'GPU4090-ASSETS'
    if (-not (Test-Path $dir)) { throw "No \GPU4090-ASSETS\ on the ESP - run install.ps1 first." }
    if (-not (Test-Path $Art)) {
        foreach ($f in $script:Files) { Remove-Item (Join-Path $dir $f) -Force -ErrorAction SilentlyContinue }
        Write-Host "No $Art - start-screen banner removed"
        return
    }
    $out = Get-LocalPath 'build\banner'
    $null = Invoke-Kachow -Arguments @('banner', $out, '--art', $Art)
    foreach ($f in $script:Files) {
        $src = Join-Path $out $f
        $dst = Join-Path $dir $f
        Copy-Item $src $dst -Force
        if ((Get-FileHash $src).Hash -ne (Get-FileHash $dst).Hash) { throw "Copy verification failed for $dst" }
    }
    Write-Host "Start-screen banner installed from $Art"
}

Export-ModuleMember -Function Install-EspBanner
