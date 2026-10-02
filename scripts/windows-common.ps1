# Shared helpers; compatible with Windows PowerShell 5.1 and PowerShell 7.
function Get-DuotermStateHome {
    if ($env:DUOTERM_SETUP_HOME) { return $env:DUOTERM_SETUP_HOME }
    return (Join-Path $HOME '.duoterm')
}

function Read-DuotermSetup {
    $file = Join-Path (Get-DuotermStateHome) 'setup.json'
    if (-not (Test-Path -LiteralPath $file)) { return $null }
    try { return (Get-Content -LiteralPath $file -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Write-DuotermSetup($Record) {
    $homePath = Get-DuotermStateHome
    [IO.Directory]::CreateDirectory($homePath) | Out-Null
    $encoding = New-Object Text.UTF8Encoding($false)
    $target = Join-Path $homePath 'setup.json'
    $temp = Join-Path $homePath ('setup-' + [guid]::NewGuid().ToString('N') + '.tmp')
    [IO.File]::WriteAllText($temp, ($Record | ConvertTo-Json -Depth 15), $encoding)
    Move-Item -LiteralPath $temp -Destination $target -Force
    $mark = ' '
    if ($Record.complete) { $mark = 'x' }
    # Build the Chinese checkbox label without requiring a BOM in PowerShell 5.1 source.
    $label = -join ([char[]]@(0x9996,0x6b21,0x73af,0x5883,0x68c0,0x67e5,0x5df2,0x5b8c,0x6210))
    $lines = @('# duoterm setup', '', "- [$mark] $label", '', "Stage: $($Record.stage)", "Version: $($Record.runtime_version)")
    foreach ($check in $Record.checks) {
        $box = ' '
        if ($check.ok) { $box = 'x' }
        $lines += "- [$box] $($check.name): $($check.detail)"
    }
    if ($Record.error) { $lines += "Pending: $($Record.error)" }
    [IO.File]::WriteAllText((Join-Path $homePath 'setup.md'), ($lines -join "`n") + "`n", $encoding)
}

function Get-DuotermSourceHash {
    $root = Join-Path $PSScriptRoot 'runtime/duoterm'
    $entries = @(Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.py' |
        Where-Object { $_.FullName -notmatch '[\\/]__pycache__[\\/]' } |
        Sort-Object FullName | ForEach-Object {
            $relative = $_.FullName.Substring($root.Length + 1).Replace('\', '/')
            $relative + ':' + (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        })
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return (-join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes(($entries -join "`n"))) | ForEach-Object { $_.ToString('x2') })) }
    finally { $sha.Dispose() }
}

function Invoke-DuotermWsl([string[]]$Arguments) {
    & wsl.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "WSL command failed (exit $LASTEXITCODE)." }
}
