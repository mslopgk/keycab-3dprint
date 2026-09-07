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
