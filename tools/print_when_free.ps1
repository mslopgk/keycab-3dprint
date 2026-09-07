<#
.SYNOPSIS
  Wait for a printer to go idle, then upload and start a job, then watch it to
  completion and force a cooldown.

.EXAMPLE
  powershell -File tools\print_when_free.ps1 `
    -File gcode\housing_onepiece_220.gcode.3mf `
    -PrinterHost 192.168.219.223 -Serial 0300DA5C2302410 -Code 40378131

.NOTES
  Polls the printer's reported state rather than guessing at durations. Only
  IDLE / FINISH / FAILED count as free; a job that is PAUSEd is left alone,
  because a pause means someone or something wanted it stopped.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$File,
  [string]$Remote,
  [Parameter(Mandatory = $true)][string]$PrinterHost,
  [Parameter(Mandatory = $true)][string]$Serial,
  [Parameter(Mandatory = $true)][string]$Code,
  [ValidateSet('1', '2', '3', '4')][string]$Speed = '4',
  [int]$WaitMinutes = 120
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$local = Join-Path $root $File
if (-not (Test-Path $local)) { throw "sliced file not found: $local" }
if (-not $Remote) { $Remote = Split-Path $File -Leaf }

$env:BAMBU_HOST = $PrinterHost
$env:BAMBU_SERIAL = $Serial
$env:BAMBU_CODE = $Code

$probe = Join-Path $PSScriptRoot 'bambu_state.py'
@'
import json, os, ssl, sys, time
import paho.mqtt.client as mqtt
HOST=os.environ["BAMBU_HOST"]; SERIAL=os.environ["BAMBU_SERIAL"]; CODE=os.environ["BAMBU_CODE"]
state={}
def on_connect(c,u,f,rc,p=None):
    c.subscribe(f"device/{SERIAL}/report")
    c.publish(f"device/{SERIAL}/request", json.dumps({"pushing":{"sequence_id":"1","command":"pushall","version":1,"push_target":1}}))
def on_message(c,u,m):
    try: d=json.loads(m.payload.decode("utf-8","replace"))
    except Exception: return
    if "print" in d and "gcode_state" in d["print"]: state["s"]=d["print"]["gcode_state"]
cl=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="keycab-state")
cl.username_pw_set("bblp", CODE)
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
cl.tls_set_context(ctx); cl.on_connect=on_connect; cl.on_message=on_message
cl.connect(HOST,8883,keepalive=30); cl.loop_start()
for _ in range(20):
    if "s" in state: break
    time.sleep(0.5)
cl.loop_stop(); cl.disconnect()
print(state.get("s","UNKNOWN"))
'@ | Set-Content -Path $probe -Encoding utf8

Write-Output "waiting for $PrinterHost to go free ..."
$deadline = (Get-Date).AddMinutes($WaitMinutes)
$last = ''
while ((Get-Date) -lt $deadline) {
  $state = (python $probe | Select-Object -Last 1).Trim()
  if ($state -ne $last) { Write-Output "  state: $state"; $last = $state }
  if ($state -in @('IDLE', 'FINISH', 'FAILED')) { break }
  Start-Sleep -Seconds 20
}
if ($last -notin @('IDLE', 'FINISH', 'FAILED')) { throw "printer never went free (last state: $last)" }

$env:BAMBU_FILE = $local
$env:BAMBU_REMOTE = $Remote
$env:BAMBU_SPEED = $Speed
$env:BAMBU_BED = 'textured_plate'
$env:BAMBU_SKIP_UPLOAD = ''

Write-Output ''
Write-Output "=== starting $Remote ==="
python (Join-Path $PSScriptRoot 'bambu_print.py')
if ($LASTEXITCODE -ne 0) { throw "start failed (exit $LASTEXITCODE)" }

Write-Output ''
Write-Output '=== watching to completion, then cooling down ==='
$env:COOL_NOZZLE_C = '40'
$env:COOL_BED_C = '35'
$env:WATCH_MINUTES = '60'
python (Join-Path $PSScriptRoot 'bambu_watch_cooldown.py')
