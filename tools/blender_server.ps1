<#
.SYNOPSIS
  Start / stop / restart the headless Blender MCP command server.

.EXAMPLE
  powershell -File tools\blender_server.ps1 start
  powershell -File tools\blender_server.ps1 restart -Blend models\keycap.blend
  powershell -File tools\blender_server.ps1 status
  powershell -File tools\blender_server.ps1 stop

.NOTES
  Restart is needed after editing tools\blender_mcp_ext\__init__.py -- the
  headless script loads that module once at startup.
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [ValidateSet('start', 'stop', 'restart', 'status', 'log')]
  [string]$Action = 'status',

  # Optional .blend to open instead of the default startup scene.
  [string]$Blend,

  [string]$BlenderExe = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
  [int]$Port = 9876,
  [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'

$root    = Split-Path -Parent $PSScriptRoot
$runDir  = Join-Path $root '.blender-mcp'
$pidFile = Join-Path $runDir 'server.pid'
$outLog  = Join-Path $runDir 'server.out.log'
$errLog  = Join-Path $runDir 'server.err.log'
$script  = Join-Path $PSScriptRoot 'serve_headless.py'

if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }

function Get-ServerProcess {
  if (-not (Test-Path $pidFile)) { return $null }
  $id = (Get-Content $pidFile | Select-Object -First 1).Trim()
  if (-not $id) { return $null }
  try { return Get-Process -Id ([int]$id) -ErrorAction Stop } catch { return $null }
}

function Stop-Server {
  $proc = Get-ServerProcess
  if ($null -eq $proc) { Write-Output 'not running'; return }
  Stop-Process -Id $proc.Id -Force -Confirm:$false
  Start-Sleep -Milliseconds 800
  Write-Output "stopped PID=$($proc.Id)"
}

function Start-Server {
  $existing = Get-ServerProcess
  if ($null -ne $existing) { Write-Output "already running PID=$($existing.Id)"; return }

  Set-Content -Path $outLog -Value '' -Encoding utf8
  Set-Content -Path $errLog -Value '' -Encoding utf8

  $blenderArgs = @('--background')
  if ($Blend) {
    if (-not (Test-Path $Blend)) { throw "blend file not found: $Blend" }
    $blenderArgs += (Resolve-Path $Blend).Path
  }
  $blenderArgs += @('--python', $script)

  $env:BLENDER_PORT = "$Port"
  $proc = Start-Process -FilePath $BlenderExe -ArgumentList $blenderArgs `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -PassThru -WindowStyle Hidden
  Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii

  $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Select-String -Path $outLog -Pattern 'BLENDER_MCP_READY' -Quiet) {
      Write-Output "ready PID=$($proc.Id) port=$Port"
      return
    }
    if ($proc.HasExited) {
      Write-Output "FAILED: blender exited with code $($proc.ExitCode)"
      Get-Content $outLog; Get-Content $errLog
      exit 1
    }
    Start-Sleep -Milliseconds 400
  }
  Write-Output "FAILED: no ready signal within ${TimeoutSeconds}s"
  Get-Content $outLog; Get-Content $errLog
  exit 1
}

switch ($Action) {
  'start'   { Start-Server }
  'stop'    { Stop-Server }
  'restart' { Stop-Server; Start-Server }
  'log'     { if (Test-Path $outLog) { Get-Content $outLog }; if ((Test-Path $errLog) -and (Get-Item $errLog).Length -gt 2) { '--- stderr ---'; Get-Content $errLog } }
  'status'  {
    $proc = Get-ServerProcess
    if ($null -eq $proc) { Write-Output 'not running' }
    else { Write-Output "running PID=$($proc.Id) port=$Port started=$($proc.StartTime.ToString('s'))" }
  }
}
