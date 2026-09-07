<#
.SYNOPSIS
  Start the pre-staged keycap plate, set the speed level, and watch to completion
  with an automatic cooldown. One command, nothing left to decide.

.EXAMPLE
  powershell -File tools\print_now.ps1
  powershell -File tools\print_now.ps1 -Plate 2

.NOTES
  The .3mf is already on the printer's SD card, so this does not re-upload; it
  verifies the remote size and starts. Both plates print the same file -- 25
  keycaps each, 50 total.

  Requires BAMBU_HOST / BAMBU_SERIAL / BAMBU_CODE, which are defaulted below.
#>
[CmdletBinding()]
param(
  [int]$Plate = 1,
  [ValidateSet('1', '2', '3', '4')][string]$Speed = '4',
  [string]$File = 'gcode\keycap_logo_x25_012.gcode.3mf',
  [string]$Remote = 'keycap_logo_x25_012.gcode.3mf',
  [string]$PrinterHost = '192.168.219.44',
  [string]$Serial = '0300DA642802767',
  [string]$Code = '28548852'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$local = Join-Path $root $File
if (-not (Test-Path $local)) { throw "sliced file not found: $local" }

$env:BAMBU_HOST = $PrinterHost
$env:BAMBU_SERIAL = $Serial
$env:BAMBU_CODE = $Code
$env:BAMBU_FILE = $local
$env:BAMBU_REMOTE = $Remote
$env:BAMBU_SPEED = $Speed
$env:BAMBU_BED = 'textured_plate'
$env:BAMBU_SKIP_UPLOAD = '1'

Write-Output "=== plate $Plate of 2 : 25 keycaps, 0.12mm, ~6h48m, 38.4g ==="
python (Join-Path $PSScriptRoot 'bambu_print.py')
if ($LASTEXITCODE -ne 0) { throw "start failed (exit $LASTEXITCODE)" }

Write-Output ''
Write-Output '=== watching to completion, then forcing cooldown ==='
$env:COOL_NOZZLE_C = '40'
$env:COOL_BED_C = '35'
$env:WATCH_MINUTES = '480'
python (Join-Path $PSScriptRoot 'bambu_watch_cooldown.py')
