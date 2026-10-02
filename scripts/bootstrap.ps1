[CmdletBinding()]
param(
    [string]$Distro,
    [string]$LinuxUser,
    [switch]$Recheck,
    [switch]$InstallDependencies,
    [switch]$RepairPath,
    [switch]$InstallWsl
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-common.ps1')
$record = Read-DuotermSetup
$fingerprint = Get-DuotermSourceHash
if ($record -and $record.complete -and $record.source_hash -eq $fingerprint -and -not $Recheck -and
    (-not $Distro -or $Distro -eq $record.backend.distro) -and
    (-not $LinuxUser -or $LinuxUser -eq $record.backend.user)) {
    Write-Output '{"complete":true,"skipped":true}'
    exit 0
}
if (-not $Distro -and $record) { $Distro = $record.backend.distro }
if (-not $LinuxUser -and $record) { $LinuxUser = $record.backend.user }
$record = [ordered]@{ schema_version=1; complete=$false; stage='checking-wsl'; source_hash=$fingerprint; runtime_version='0.2.0'; checks=@(); error=$null }
Write-DuotermSetup $record
try {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'WSL is unavailable. Authorize WSL/Ubuntu installation, then use -InstallWsl in elevated PowerShell.' }
    try {
        $distros = @(Invoke-DuotermWsl -Arguments @('--list', '--quiet') | ForEach-Object { $_.Replace([string][char]0, '').Trim() } | Where-Object { $_ })
    } catch {
        if (-not $InstallWsl) { throw }
        $distros = @()  # WSL features may not be enabled yet.
    }
    if (-not $distros.Count -and $InstallWsl) {
        $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
        if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Open elevated PowerShell and run wsl --install -d Ubuntu; then reboot and create your Linux user.' }
        Invoke-DuotermWsl -Arguments @('--install', '-d', 'Ubuntu', '--no-launch') | Out-Host
        throw 'WSL installation requested. Restart if needed, launch Ubuntu, create your Linux user, then rerun bootstrap.'
    }
    if (-not $Distro) {
        $choices = @($distros | Where-Object { $_ -match '^(Ubuntu|Debian)' })
        if ($choices.Count -ne 1) { throw 'Specify -Distro with an existing Ubuntu/Debian distribution, or authorize wsl --install -d Ubuntu.' }
        $Distro = $choices[0]
    }
    if ($Distro -notin $distros) { throw "Distribution '$Distro' is not installed. Install/initialize it, then retry." }
    $base = @('-d', $Distro)
    if ($LinuxUser) { $base += @('-u', $LinuxUser) }
    $userName = ([string](Invoke-DuotermWsl ($base + @('--exec','id','-un')))).Trim()
    if ($userName -eq 'root') { throw 'Select a non-root Linux user with -LinuxUser after first-launch user creation.' }
    $linuxScript = ([string](Invoke-DuotermWsl ($base + @('--exec','wslpath','-u',(Join-Path $PSScriptRoot 'install.sh'))))).Trim()
    $arguments = $base + @('--exec','bash',$linuxScript)
    if ($Recheck) { $arguments += '--recheck' }
    if ($InstallDependencies) { $arguments += '--install-packages' }
    if ($RepairPath) { $arguments += '--repair-path' }
    $output = Invoke-DuotermWsl $arguments
    $linuxRecord = ($output -join "`n") | ConvertFrom-Json
    if (-not $linuxRecord.complete) { throw 'Linux initialization incomplete. Read the WSL ~/.duoterm/setup.md and repair the reported check.' }
    $record = [ordered]@{
        schema_version=1; complete=$false; stage='checking-bridge'; source_hash=$fingerprint;
        runtime_version=$linuxRecord.runtime_version; runtime_path=$linuxRecord.runtime_path; python=$linuxRecord.python;
        cli=$linuxRecord.cli; checks=@($linuxRecord.checks); error=$null;
        backend=@{platform='wsl'; distro=$Distro; user=$userName}
    }
    $payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('["--version"]'))
    $version = Invoke-DuotermWsl -Arguments @('-d',$Distro,'-u',$userName,'--exec',$record.python,($record.runtime_path + '/bridge.py'),$payload)
    if (($version -join '').Trim() -ne "duoterm $($record.runtime_version)") { throw 'Installed runtime version could not be verified through the Windows bridge.' }
    $record.checks += @{name='windows-wsl-bridge'; ok=$true; detail="${Distro}:$userName"}
    $record.complete = $true
    $record.stage = 'ready'
    Write-DuotermSetup $record
    Write-Output ($record | ConvertTo-Json -Depth 15 -Compress)
    exit 0
} catch {
    $record.complete = $false
    $record.stage = 'blocked'
    $record.error = $_.Exception.Message
    Write-DuotermSetup $record
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 125
}
