# State-machine checks without installing WSL or changing the user's profile.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$work = Join-Path $root ('.verification/bootstrap-' + [guid]::NewGuid().ToString('N'))
$prior = $env:DUOTERM_SETUP_HOME
$env:DUOTERM_SETUP_HOME = $work
$global:duotermMockCallCount = 0
$global:duotermMockFail = $false
function global:wsl.exe {
    $global:duotermMockCallCount++
    $global:LASTEXITCODE = 0
    if ($global:duotermMockFail) { $global:LASTEXITCODE = 1; return }
    if ($args[0] -eq '--list') { return 'Ubuntu' }
    if ($args -contains 'id') { return 'testuser' }
    if ($args -contains 'wslpath') { return '/test/install.sh' }
    if ($args -contains 'bash') {
        return '{"complete":true,"runtime_version":"0.2.0","runtime_path":"/test/runtime","python":"/test/python","cli":"/test/bin/duoterm","checks":[]}'
    }
    return 'duoterm 0.2.0'
}
try {
    $bootstrap = Join-Path $root 'scripts/bootstrap.ps1'
    $result = & $bootstrap -Distro Ubuntu
    if ($LASTEXITCODE -or -not (($result -join '') | ConvertFrom-Json).complete) { throw 'First bootstrap did not complete' }
    $state = Get-Content (Join-Path $work 'setup.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.backend.user -ne 'testuser' -or $state.backend.distro -ne 'Ubuntu') { throw 'Backend identity not recorded' }
    $label = -join ([char[]]@(0x9996,0x6b21,0x73af,0x5883,0x68c0,0x67e5,0x5df2,0x5b8c,0x6210))
    if (-not (Get-Content (Join-Path $work 'setup.md') -Raw -Encoding UTF8).Contains("- [x] $label")) { throw 'Checklist not checked after verification' }
    $before = $global:duotermMockCallCount
    $again = & $bootstrap
    if (-not (($again -join '') | ConvertFrom-Json).skipped -or $global:duotermMockCallCount -ne $before) { throw 'Cached setup invoked WSL' }
    $global:duotermMockFail = $true
    $ErrorActionPreference = 'Continue'
    & $bootstrap -Recheck 2>$null | Out-Null
    $ErrorActionPreference = 'Stop'
    $state = Get-Content (Join-Path $work 'setup.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($state.complete -or $state.stage -ne 'blocked') { throw 'Failed recheck left setup complete' }
    if ((Get-Content (Join-Path $work 'setup.md') -Raw -Encoding UTF8).Contains("- [x] $label")) { throw 'Failed recheck left checkbox checked' }
    Write-Output 'PASS: bootstrap first completion, private state, cached skip without WSL, failed recheck unchecked'
} finally {
    Remove-Item Function:\wsl.exe -ErrorAction SilentlyContinue
    $env:DUOTERM_SETUP_HOME = $prior
}
