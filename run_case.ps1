param(
    [Parameter(Mandatory=$true)][string]$BlenderPath,
    [string]$PythonPath,
    [switch]$RebuildFromMaps
)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
if (-not $PythonPath) { $PythonPath = Join-Path $taskRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $BlenderPath)) { throw 'Blender executable not found' }
if (-not (Test-Path -LiteralPath $PythonPath)) { throw 'Run setup/bootstrap.ps1 or specify -PythonPath' }
$scriptsDir = Join-Path $taskRoot '.agents/skills/photo-to-ornament/scripts'
$beforeDir = Join-Path $taskRoot 'cases/ding/mesh_before'
if ($RebuildFromMaps -or -not (Test-Path -LiteralPath (Join-Path $beforeDir 'ding_quad_uv.npz'))) {
    $beforeDir = Join-Path $taskRoot 'runs/ding/rebuilt_before'
    & $PythonPath (Join-Path $scriptsDir 'build_quad_uv.py') --maps (Join-Path $taskRoot 'cases/ding/maps') --out $beforeDir --width-m 1 --base-m 0.01285 --relief-m 0.02215 --area 6e-7 --wall-layers 16
    if ($LASTEXITCODE -ne 0) { throw 'Map-to-quad build failed' }
}
$meshDir = Join-Path $taskRoot 'runs/ding/mesh'
& $PythonPath (Join-Path $scriptsDir 'scale_relief.py') --source $beforeDir --out $meshDir --factor 0.5
if ($LASTEXITCODE -ne 0) { throw 'Relief scaling failed' }
$resultDir = Join-Path $taskRoot 'runs/ding/result'
& $BlenderPath --factory-startup -b --python (Join-Path $scriptsDir 'build_scene.py') -- --source $meshDir --out $resultDir
if ($LASTEXITCODE -ne 0) { throw 'Blender export or validation failed' }
Write-Output "Result: $resultDir/ornament_highpoly.fbx and ornament_highpoly.blend"
