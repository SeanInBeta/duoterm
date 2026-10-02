[CmdletBinding()]
param([string]$Distro = 'Ubuntu', [string]$LinuxUser = 'sean')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$identifier = [guid]::NewGuid().ToString('N')
$work = Join-Path $root ('.verification/bridge-' + $identifier + ' 中文 spaces')
[IO.Directory]::CreateDirectory($work) | Out-Null
$linuxWork = ((& wsl.exe -d $Distro -u $LinuxUser --exec wslpath -u $work) -join '').Trim()
if ($LASTEXITCODE) { throw 'Cannot map test workspace to WSL' }
$linuxPrepare = ((& wsl.exe -d $Distro -u $LinuxUser --exec wslpath -u (Join-Path $PSScriptRoot 'prepare_windows.py')) -join '').Trim()
$oldValues = @{}
foreach ($key in @('DUOTERM_SETUP_HOME','DUOTERM_HOME','DUOTERM_TMUX_SOCKET')) { $oldValues[$key] = [Environment]::GetEnvironmentVariable($key) }
$env:DUOTERM_SETUP_HOME = Join-Path $work 'windows-state'
$env:DUOTERM_HOME = $linuxWork + '/logs'
$env:DUOTERM_TMUX_SOCKET = 'duoterm-win-' + $identifier
$nativeShell = (Get-Process -Id $PID).Path
$skillScripts = Join-Path $work '技能包/scripts'
[IO.Directory]::CreateDirectory((Split-Path $skillScripts -Parent)) | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'scripts') -Destination $skillScripts -Recurse
$invoke = Join-Path $skillScripts 'invoke.ps1'
function Call-Cli([string[]]$Arguments, [int]$Expected = 0) {
    # Call the script exactly as the agent does, without an extra native argument boundary.
    $output = & $invoke @Arguments
    if ($LASTEXITCODE -ne $Expected) { throw "Unexpected CLI exit $LASTEXITCODE (expected $Expected): $output" }
    return ($output -join "`n")
}
try {
    & wsl.exe -d $Distro -u $LinuxUser --exec python3 $linuxPrepare $linuxWork $Distro $LinuxUser | Out-Null
    if ($LASTEXITCODE) { throw 'Test runtime initialization failed' }
    $before = [IO.File]::ReadAllText((Join-Path $env:DUOTERM_SETUP_HOME 'setup.json'))
    $cached = & $nativeShell -NoProfile -File (Join-Path $skillScripts 'bootstrap.ps1')
    if ($LASTEXITCODE -or -not (($cached -join '') | ConvertFrom-Json).skipped) { throw 'Bootstrap did not skip completed setup' }
    if ($before -ne [IO.File]::ReadAllText((Join-Path $env:DUOTERM_SETUP_HOME 'setup.json'))) { throw 'Cached bootstrap changed state' }
    foreach ($name in @('A','B','C')) {
        Call-Cli -Arguments @('-s',$name,'start','--command',"env PS1='$ ' HISTFILE=/dev/null bash --norc --noprofile") | Out-Null
    }
    $command = @'
printf '%s\n' 'Chinese: 中文 spaces' '"double" and '\''single'\''' '$HOME ; | & `backtick`'; false
'@
    $result = (Call-Cli -Arguments @('-s','A','run',$command,'--json') -Expected 1) | ConvertFrom-Json
    $expected = @'
Chinese: 中文 spaces
"double" and 'single'
$HOME ; | & `backtick`
'@
    if ($result.output.TrimEnd() -ne $expected.TrimEnd()) { throw "Argument roundtrip mismatch: $($result.output)" }
    Call-Cli -Arguments @('-s','B','run','echo only-B') | Out-Null
    Call-Cli -Arguments @('-s','C','run','echo only-C') | Out-Null
    $list = (Call-Cli -Arguments @('list','--json')) | ConvertFrom-Json
    if (($list.sessions.session | Sort-Object) -join ',' -ne 'A,B,C') { throw 'Three-session discovery failed' }
    if ((Call-Cli -Arguments @('-s','B','read','--new')) -match 'only-C') { throw 'Cross-session log leakage' }
    Write-Output "PASS: Windows $($PSVersionTable.PSVersion), cached setup, Unicode/quotes/spaces/dollar/pipe forwarding, exits, A/B/C discovery"
} finally {
    $ErrorActionPreference = 'Continue'
    & wsl.exe -d $Distro -u $LinuxUser --exec tmux -L $env:DUOTERM_TMUX_SOCKET kill-server 2>$null
    foreach ($key in $oldValues.Keys) { [Environment]::SetEnvironmentVariable($key, $oldValues[$key]) }
}
