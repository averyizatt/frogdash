"""Generate a synthetic MLG file for opening in MegaLogViewer (no hardware needed)."""
import argparse
import math
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hardware.frogdash.log_channels import FIELDS, info, row_values
from hardware.frogdash.mlg import Encoder


def create(path):
    encoder = Encoder(FIELDS, time.time(), 'SYNTHETIC DEMO - NOT VEHICLE DATA\n' + info('demo', 20))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encoder.header)
        for i in range(600):
            seconds = i / 20
            ramp = (math.sin(seconds / 3) + 1) / 2
            readings = {
                'engine.rpm': 900 + ramp * 3500, 'ecu.map_kpa': 40 + ramp * 100,
                'engine.boost_kpa': -60 + ramp * 100, 'ecu.throttle_pct': ramp * 60,
                'engine.afr': 14.7 - ramp * 2.5, 'ecu.afr_target': 14.7 - ramp * 2.5,
                'engine.coolant_c': 90, 'engine.iat_c': 35, 'vehicle.battery_v': 14.2,
                'engine.oil_pressure_psi': 30 + ramp * 30, 'engine.fuel_pressure_psi': 40,
                'vehicle.speed_kph': ramp * 90, 'meth.state': 'ARMED', 'meth.duty_pct': 0,
                'meth.tank_pct': 85, 'meth.flow': 'OK', 'meth.fault_flags': 0,
                'knock.energy': 20 + ramp * 8, 'knock.threshold': 60,
                'lighting.brake': False, 'lighting.turn_left': 12 <= seconds < 15,
                'lighting.running': True,
            }
            values = {key: {'value': value, 'quality': 'live'} for key, value in readings.items()}
            if 20 <= seconds < 23:
                values['engine.oil_pressure_psi']['quality'] = 'stale'
            snapshot = {'transport': {'connected': True}, 'values': values}
            stream.write(encoder.row(seconds, row_values(snapshot, seconds)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    create(args.output)
    print(f'Created {args.output}: 600 synthetic samples, 30 seconds, MLG v2.')
