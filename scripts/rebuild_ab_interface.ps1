param(
    [string]$QgisPython = 'D:\LaotuZhBi\software\QGIS\bin\python-qgis-ltr.bat'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
foreach ($scriptName in @('build_road_static_features.py', 'verify_ab_interface.py', 'create_ab_interface_project.py')) {
    & $QgisPython (Join-Path $PSScriptRoot $scriptName)
    if ($LASTEXITCODE -ne 0) { throw "Failed: $scriptName ($LASTEXITCODE)" }
}
Write-Output (Join-Path $projectRoot 'data\derived\static\a_to_b_interface_review.qgz')
