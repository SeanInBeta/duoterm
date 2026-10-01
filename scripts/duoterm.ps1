# PowerShell shim: lets a Windows-native agent (or you) call duoterm living in WSL.
# Put this folder on your PATH, then use `duoterm status`, `duoterm run "ls"` ... from PowerShell.
# Set $env:DUOTERM_WSL_DISTRO to pick a distro (default: your WSL default distro).
$distroArgs = @()
if ($env:DUOTERM_WSL_DISTRO) { $distroArgs = @("-d", $env:DUOTERM_WSL_DISTRO) }
& wsl.exe @distroArgs -e bash -lc 'exec duoterm "$@"' duoterm @args
exit $LASTEXITCODE
