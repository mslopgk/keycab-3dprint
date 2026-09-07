<#
.SYNOPSIS
  Slice one STL for the Bambu Lab A1 mini with the vendor's real high-speed values.

.EXAMPLE
  powershell -File tools\slice_part.ps1 -Stl models\switch_housing.stl -Out switch_housing.gcode.3mf

.NOTES
  Two corrections are baked in because both silently ruin a print:

  1. OrcaSlicer's bundled presets are `inherits` deltas. Passing a leaf process
     JSON to --load-settings loads only the delta and falls back to built-in
     defaults -- 0.2mm layers at 60mm/s instead of the vendor's 0.28mm at
     200mm/s. tools/flatten_orca_preset.py resolves the chain first. The MACHINE
     preset must stay the un-flattened leaf; the CLI rejects a flattened one
     with "...json's from  unsupported".
  2. --curr-bed-type must be passed explicitly. The default is "Cool Plate",
     which commands a 35C bed; PLA on the A1 mini's textured PEI plate needs 65C
     or a small part with little contact area lets go.

  The verify block at the end prints the settings back. If layer_height reads
  0.2 or outer_wall_speed reads 60, the preset chain did not resolve -- do not print.
#>
[CmdletBinding()]
param(
  # One or more STLs. Two or more are arranged onto a single plate, which saves a
  # whole heat-up and calibration cycle versus printing them as separate jobs.
  [Parameter(Mandatory = $true)][string[]]$Stl,
  [Parameter(Mandatory = $true)][string]$Out,
  [string]$Process   = "0.28mm Extra Draft @BBL A1M",
  [string]$Filament  = "Generic PLA High Speed @BBL A1M",
  [string]$Machine   = "Bambu Lab A1 mini 0.4 nozzle",
  [string]$BedType   = "Textured PEI Plate",
  [double]$BrimWidth = 3,
  # 0 keeps whatever the filament preset says. Set it to override both the main
  # and first-layer nozzle temperature.
  [int]$NozzleTemp   = 0,
  # Repeat every STL this many times and let the slicer arrange them.
  [int]$Copies       = 1,
  # Longer retraction, taller Z-hop, longer wipe, and detour around walls during
  # travel. Aimed at a plate of many small parts, where most of the tool path is
  # travel between objects and every travel is a chance to string.
  [switch]$AntiString,
  # Extra key=value overrides applied to the flattened process preset, e.g.
  # 'sparse_infill_density=5%'. Applied last, so they win over -AntiString.
  # Use for throwaway diagnostic parts where only the geometry matters.
  [string[]]$ProcessOverride = @(),
  # Extra key=value overrides applied to the flattened filament preset, after
  # -AntiString and after -NozzleTemp, so they win over both. Use for things
  # like a hotter first layer than the rest of the print.
  [string[]]$FilamentOverride = @(),
  [string]$OrcaDir   = "C:\Users\user\AppData\Local\Programs\OrcaSlicer-portable"
)

$ErrorActionPreference = 'Stop'

$root     = Split-Path -Parent $PSScriptRoot
$outDir   = Join-Path $root 'gcode'
$flatDir  = Join-Path $outDir '_presets'
$profiles = Join-Path $OrcaDir 'resources\profiles'
$exe      = Join-Path $OrcaDir 'orca-slicer.exe'

foreach ($p in (@($exe, $profiles) + $Stl)) {
  if (-not (Test-Path $p)) { throw "not found: $p" }
}
foreach ($d in @($outDir, $flatDir)) {
  if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d | Out-Null }
}

python (Join-Path $PSScriptRoot 'flatten_orca_preset.py') $profiles 'BBL' `
  --machine $Machine --process $Process --filament $Filament --outdir $flatDir |
  Select-String -Pattern 'keys|chain' | ForEach-Object { '  ' + $_.Line.Trim() }
if ($LASTEXITCODE -ne 0) { throw "preset flattening failed" }

$leafMachine = Join-Path $profiles "BBL\machine\$Machine.json"
if (-not (Test-Path $leafMachine)) { throw "machine preset not found: $leafMachine" }

if ($AntiString) {
  # These go into the FILAMENT preset, not the machine preset. The machine
  # preset handed to --load-settings below is $leafMachine -- the vendor's
  # original -- because the CLI rejects a flattened one. So patching
  # $flatDir\machine.json wrote a file nothing ever read, and every
  # retraction/z-hop/wipe override was silently dropped while the run still
  # reported "anti-stringing overrides" and looked fine.
  #
  # Orca's filament presets carry a full set of "filament_*" overrides, empty
  # ("nil") by default, that win over the machine values when set. filament.json
  # IS passed, via --load-filaments, so this actually reaches the gcode.
  Write-Output 'anti-stringing overrides (filament):'
  python (Join-Path $PSScriptRoot 'patch_preset.py') (Join-Path $flatDir 'filament.json') `
    'filament_retraction_length=1' 'filament_z_hop=0.6' 'filament_wipe_distance=3' `
    'filament_retraction_speed=40' 'filament_deretraction_speed=40' `
    'filament_wipe=1' 'filament_retract_when_changing_layer=1' `
    'filament_retraction_minimum_travel=1'
  if ($LASTEXITCODE -ne 0) { throw 'filament anti-stringing patch failed' }
  Write-Output 'anti-stringing overrides (process):'
  python (Join-Path $PSScriptRoot 'patch_preset.py') (Join-Path $flatDir 'process.json') `
    'reduce_crossing_wall=1' 'max_travel_detour_distance=0' `
    'reduce_infill_retraction=0'
  if ($LASTEXITCODE -ne 0) { throw 'process anti-stringing patch failed' }
}

if ($ProcessOverride.Count -gt 0) {
  Write-Output 'process overrides:'
  python (Join-Path $PSScriptRoot 'patch_preset.py') (Join-Path $flatDir 'process.json') @ProcessOverride
  if ($LASTEXITCODE -ne 0) { throw 'process override patch failed' }
}

if ($NozzleTemp -gt 0) {
  # Patch the flattened filament config rather than pass a CLI flag: the option
  # names the CLI accepts are undocumented here, and a silently ignored flag
  # would print at the preset temperature without any warning.
  $patch = @"
import json, sys
path, temp = sys.argv[1], sys.argv[2]
with open(path, 'r', encoding='utf-8') as h:
    cfg = json.load(h)
low = int(cfg.get('nozzle_temperature_range_low', ['0'])[0])
high = int(cfg.get('nozzle_temperature_range_high', ['999'])[0])
if not (low <= int(temp) <= high):
    sys.exit(f'{temp}C is outside the filament range {low}-{high}C')
for key in ('nozzle_temperature', 'nozzle_temperature_initial_layer'):
    if key in cfg:
        cfg[key] = [temp] * len(cfg[key])
with open(path, 'w', encoding='utf-8') as h:
    json.dump(cfg, h, indent=1, ensure_ascii=False)
print(f'  nozzle temperature overridden to {temp}C (range {low}-{high})')
"@
  $patchFile = Join-Path $flatDir '_patch_temp.py'
  Set-Content -Path $patchFile -Value $patch -Encoding utf8
  python $patchFile (Join-Path $flatDir 'filament.json') "$NozzleTemp"
  if ($LASTEXITCODE -ne 0) { throw "nozzle temperature override rejected" }
}

if ($FilamentOverride.Count -gt 0) {
  Write-Output 'filament overrides:'
  python (Join-Path $PSScriptRoot 'patch_preset.py') (Join-Path $flatDir 'filament.json') @FilamentOverride
  if ($LASTEXITCODE -ne 0) { throw 'filament override patch failed' }
}

$resolved = @()
foreach ($one in $Stl) {
  $full = (Resolve-Path $one).Path
  for ($i = 0; $i -lt $Copies; $i++) { $resolved += $full }
}
$stlArgs = ($resolved | ForEach-Object { '"' + $_ + '"' }) -join ' '
$arrange = if ($resolved.Count -gt 1) { ' --arrange 1' } else { '' }
Write-Output "objects on plate: $($resolved.Count)"
$argStr =
  '--load-settings "' + $leafMachine + ';' + (Join-Path $flatDir 'process.json') + '"' +
  ' --load-filaments "' + (Join-Path $flatDir 'filament.json') + '"' +
  ' --curr-bed-type "' + $BedType + '"' + $arrange +
  ' --slice 0 --brim-type outer_only --brim-width ' + $BrimWidth +
  ' --ensure-on-bed --export-3mf "' + $Out + '"' +
  ' --outputdir "' + $outDir + '" ' + $stlArgs

$stdout = Join-Path $outDir '_slice.out.log'
$stderr = Join-Path $outDir '_slice.err.log'
Set-Content -Path $stdout -Value '' -Encoding utf8
Set-Content -Path $stderr -Value '' -Encoding utf8

$proc = Start-Process -FilePath $exe -ArgumentList $argStr `
  -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
  -PassThru -NoNewWindow -Wait

if ($proc.ExitCode -ne 0) {
  Write-Output "SLICE FAILED (exit $($proc.ExitCode))"
  Get-Content $stdout; Get-Content $stderr
  exit 1
}

$gcode = Join-Path $outDir 'plate_1.gcode'
if (-not (Test-Path $gcode)) { throw "slicer produced no plate_1.gcode" }

Write-Output "sliced -> $(Join-Path $outDir $Out)"
Write-Output '--- verify before printing ---'
Select-String -Path $gcode -Pattern '^; (total layer number|layer_height =|outer_wall_speed|nozzle_temperature =|curr_bed_type|enable_support|brim_width|printer_model)' |
  ForEach-Object { '  ' + $_.Line }
Select-String -Path $gcode -Pattern '^M190' | Select-Object -First 1 |
  ForEach-Object { '  ' + $_.Line }
Select-String -Path $gcode -Pattern '(model printing time|filament used \[g\])' |
  Where-Object { $_.Line -match '^;' } | ForEach-Object { '  ' + $_.Line.Trim() }
