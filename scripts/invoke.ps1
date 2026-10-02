# Pass CLI arguments as data, preserving quotes, Unicode, whitespace and shell syntax.
# Usage: & /absolute/skill/scripts/invoke.ps1 -s A run 'printf "%s" "$HOME"'
$ErrorActionPreference = 'Stop'
$cliArguments = @($args | ForEach-Object { [string]$_ })
. (Join-Path $PSScriptRoot 'windows-common.ps1')
$record = Read-DuotermSetup
if (-not $record -or -not $record.complete -or $record.backend.platform -ne 'wsl') {
    Write-Error 'duoterm has not completed Windows initialization. Run scripts/bootstrap.ps1.'
    exit 125
}
$forwardEnv = @{}
foreach ($key in @('DUOTERM_TMUX_SOCKET','DUOTERM_TMUX_CONFIG','DUOTERM_HOME','DUOTERM_TERM','DUOTERM_AUTO_INTEGRATE','DUOTERM_PROMPT_RE')) {
    $value = [Environment]::GetEnvironmentVariable($key)
    if ($null -ne $value) { $forwardEnv[$key] = $value }
}
$json = ConvertTo-Json -InputObject @{args=$cliArguments; env=$forwardEnv} -Compress -Depth 5
$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
& wsl.exe -d $record.backend.distro -u $record.backend.user --exec $record.python ($record.runtime_path + '/bridge.py') $payload
exit $LASTEXITCODE
