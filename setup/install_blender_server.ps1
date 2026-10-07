param([string]$PythonPath)
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $PythonPath) { $PythonPath = Join-Path $taskRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Run bootstrap.ps1 or provide a PythonPath' }
$serverDir = Join-Path $taskRoot '.blender-mcp-venv'
if (-not (Test-Path -LiteralPath (Join-Path $serverDir 'Scripts/python.exe'))) {
    & $PythonPath -m venv $serverDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Blender MCP environment' }
}
$serverPython = Join-Path $serverDir 'Scripts/python.exe'
& $serverPython -m pip install 'blender-mcp==1.9.1'
if ($LASTEXITCODE -ne 0) { throw 'Blender MCP installation failed' }
Write-Output (Join-Path $serverDir 'Scripts/blender-mcp.exe')
Write-Output 'Set this as your local blender MCP command after inspecting existing settings. Install/enable blender_addon.py in Blender separately.'
