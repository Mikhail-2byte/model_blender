param([string]$BlenderPath)

$WorkshopRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$LocalRoot = Join-Path $WorkshopRoot '.local'
if (-not $BlenderPath) { $BlenderPath = $env:BLENDER_EXECUTABLE }
if (-not $BlenderPath) {
    $BlenderPath = Join-Path $LocalRoot 'blender-5.2.4-windows-x64/blender.exe'
}
$env:BLENDER_EXECUTABLE = (Get-Item -LiteralPath $BlenderPath -ErrorAction Stop).FullName
foreach ($kind in @('CONFIG', 'SCRIPTS', 'EXTENSIONS', 'DATAFILES')) {
    $folder = Join-Path $LocalRoot "blender-user/$($kind.ToLowerInvariant())"
    New-Item -ItemType Directory -Path $folder -Force | Out-Null
    [Environment]::SetEnvironmentVariable("BLENDER_USER_$kind", $folder, 'Process')
}
