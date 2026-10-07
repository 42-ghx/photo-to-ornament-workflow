param([string]$PythonCommand = 'python')
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$venvDir = Join-Path $taskRoot '.venv'
& $PythonCommand -c "import sys; assert sys.version_info[:2] == (3,12), 'Use Python 3.12 for this tested bundle'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 check failed' }
if (-not (Test-Path -LiteralPath (Join-Path $venvDir 'Scripts/python.exe'))) {
    & $PythonCommand -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment' }
}
$taskPython = Join-Path $venvDir 'Scripts/python.exe'
& $taskPython -m pip install -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
& $taskPython -c "import numpy,scipy,skimage,shapely,triangle,trimesh,PIL; print('Geometry runtime ready')"
if ($LASTEXITCODE -ne 0) { throw 'Dependency imports failed' }
Write-Output 'Next: install_skill.py and MIGRATION.md. No client settings were replaced.'
