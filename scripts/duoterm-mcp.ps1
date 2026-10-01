# PowerShell shim for the MCP server, for Windows-native agents:
#   command: powershell.exe  args: ["-NoProfile", "-File", "C:\\path\\to\\duoterm-mcp.ps1"]
# or directly: command: wsl.exe  args: ["-e", "bash", "-lc", "exec duoterm-mcp"]
$distroArgs = @()
if ($env:DUOTERM_WSL_DISTRO) { $distroArgs = @("-d", $env:DUOTERM_WSL_DISTRO) }
& wsl.exe @distroArgs -e bash -lc 'exec duoterm-mcp'
exit $LASTEXITCODE
