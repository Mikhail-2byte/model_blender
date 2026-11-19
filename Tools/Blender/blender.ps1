param(
    [ValidateSet('version', 'open', 'template', 'check', 'export')]
    [string]$Mode = 'version',
    [string]$Source,
    [string]$Output,
    [string]$BlenderPath,
    [switch]$NoApplyTransform
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'blender-env.ps1') $BlenderPath
$template = Join-Path $WorkshopRoot 'ArtSource/Blender/DRONEWORKS.blend'
if ($Mode -eq 'version') {
    & $env:BLENDER_EXECUTABLE --version
} elseif ($Mode -eq 'open') {
    if (-not $Source) { $Source = $template }
    & $env:BLENDER_EXECUTABLE --disable-autoexec (Resolve-Path -LiteralPath $Source).Path
} else {
    if ($Mode -eq 'export' -and (-not $Source -or -not $Output)) {
        throw 'Export requires -Source <blend> and -Output <fbx>.'
    }
    if ($Mode -eq 'check' -and -not $Output) {
        $Output = Join-Path $LocalRoot "checks/$(Get-Date -Format 'yyyyMMdd-HHmmss-fff')"
    }
    $blenderArgs = @('--background', '--factory-startup', '--disable-autoexec')
    if ($Mode -eq 'export') {
        $blenderArgs += (Resolve-Path -LiteralPath $Source).Path
    }
    $blenderArgs += @('--python-exit-code', '1', '--python', (Join-Path $PSScriptRoot 'workflow.py'), '--', $Mode)
    if ($Output) { $blenderArgs += $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output) }
    if ($NoApplyTransform) { $blenderArgs += '--no-apply-transform' }
    & $env:BLENDER_EXECUTABLE @blenderArgs
}
exit $LASTEXITCODE
