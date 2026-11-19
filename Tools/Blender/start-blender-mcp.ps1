$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'blender-env.ps1')
$studio = Join-Path $LocalRoot 'studio'
Set-Location -LiteralPath (Join-Path $studio 'plugins/blender-agent-studio')
& (Join-Path $studio 'bun.exe') 'mcp/server.ts'
exit $LASTEXITCODE
