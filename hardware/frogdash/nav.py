"""Position and speed that survive GPS dropouts.

While the USB GPS has a fix it is used as is, and the gateway's wheel speed is calibrated
against it. When the fix is lost (tunnel, garage, cold start), speed falls back to the
calibrated wheel speed and the position is dead-reckoned: distance from wheel speed,
direction by following the road in the bundled street map, or the last heading when the
car is not on a mapped road. There is no gyro, so off-road turns cannot be seen; the
estimate is labelled and carries a growing accuracy figure. The last position is saved
so the map has a starting point before the first fix after a restart.
"""
import asyncio
import json
import math
from pathlib import Path

from .driving import atomic_write

M_PER_DEG = 111320.0
CAL_MIN_KPH = 30.0          # Calibrate wheel speed only at steady road speeds.
SCALE_LIMITS = (.7, 1.4)
SNAP_M, SNAP_ANGLE = 35.0, 50.0
TURN_LIMIT = 100.0          # Largest heading change accepted when a road continues.
COAST_S = 4.0               # Without wheel speed: carry the last GPS speed this long through a dropout.


def distance_m(a, b):
    return math.hypot((b[1] - a[1]) * math.cos(math.radians(a[0])) * M_PER_DEG, (b[0] - a[0]) * M_PER_DEG)


def bearing(a, b):
    """Degrees clockwise from north, from a to b (lat, lon)."""
    return math.degrees(math.atan2((b[1] - a[1]) * math.cos(math.radians(a[0])), b[0] - a[0])) % 360


def angle_between(a, b):
    return abs((a - b + 180) % 360 - 180)


def moved(point, heading, metres):
    lat, lon = point
    return (lat + metres * math.cos(math.radians(heading)) / M_PER_DEG,
            lon + metres * math.sin(math.radians(heading)) / (M_PER_DEG * math.cos(math.radians(lat))))


class RoadMap:
    """Road centre lines from tools/make_map.py output, indexed for snapping and following."""
    CELL = .002  # degrees, about 220 m

    def __init__(self, data):
        scale = data['scale']
        base = (round(data['bounds'][0] * scale), round(data['bounds'][1] * scale))
        self.ways, self.grid, self.nodes = [], {}, {}
        for kind, _name, deltas in data['ways']:
            if kind > 4:
                continue  # Rivers and railways.
            lat, lon = base
            points = []
            for i in range(0, len(deltas), 2):
                lat += deltas[i]; lon += deltas[i + 1]
                points.append((lat / scale, lon / scale))
            index = len(self.ways)
            self.ways.append(points)
            for vertex, point in enumerate(points):
                self.nodes.setdefault(self.key(point), []).append((index, vertex))
                if vertex:
                    for cell in {self.cell(points[vertex - 1]), self.cell(point)}:
                        self.grid.setdefault(cell, []).append((index, vertex - 1))

    @staticmethod
    def key(point):
        return round(point[0] * 100000), round(point[1] * 100000)

    def cell(self, point):
        return math.floor(point[0] / self.CELL), math.floor(point[1] / self.CELL)

    def snap(self, point, heading):
        """Nearest road segment running along the heading: (way, from_vertex, direction, point) or None."""
        cy, cx = self.cell(point)
        cos_lat = math.cos(math.radians(point[0]))
        best, best_distance = None, SNAP_M
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for way, segment in self.grid.get((cy + dy, cx + dx), ()):
                    a, b = self.ways[way][segment], self.ways[way][segment + 1]
                    ax, ay = (a[1] - point[1]) * cos_lat * M_PER_DEG, (a[0] - point[0]) * M_PER_DEG
                    bx, by = (b[1] - point[1]) * cos_lat * M_PER_DEG, (b[0] - point[0]) * M_PER_DEG
                    ex, ey = bx - ax, by - ay
                    length = ex * ex + ey * ey
                    if not length:
                        continue
                    t = max(0., min(1., -(ax * ex + ay * ey) / length))
                    gap = math.hypot(ax + t * ex, ay + t * ey)
                    if gap >= best_distance:
                        continue
                    forward = bearing(a, b)
                    if angle_between(forward, heading) <= SNAP_ANGLE:
                        direction, start = 1, segment
                    elif angle_between((forward + 180) % 360, heading) <= SNAP_ANGLE:
                        direction, start = -1, segment + 1
                    else:
                        continue
                    best_distance = gap
                    best = (way, start, direction, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
        return best

    def onward(self, way, vertex, heading):
        """Where the road continues from a way's end: (way, vertex, direction) with the least turn."""
        best, best_turn = None, TURN_LIMIT
        node = self.ways[way][vertex]
        for other, at in self.nodes.get(self.key(node), ()):
            points = self.ways[other]
            for direction in (1, -1):
                following = at + direction
                if not 0 <= following < len(points) or (other == way and following == vertex):
                    continue
                turn = angle_between(bearing(node, points[following]), heading)
                if turn < best_turn:
                    best, best_turn = (other, at, direction), turn
        return best


class Navigator:
    def __init__(self, clock, wall, path=None, map_dir=None):
        self.clock, self.wall = clock, wall
        self.path = Path(path) if path else None
        self.map_dir = Path(map_dir) if map_dir else Path(__file__).resolve().parents[1] / 'maps'
        self.roads = None              # Loaded on first need.
        self.position = None           # (lat, lon)
        self.track = 0.0
        self.source = 'none'           # gps | estimated | last-known | none
        self.speed_source = 'none'     # gps | wheel | held | none
        self.fixed_this_run = False
        self.since_fix_m = self.since_fix_s = 0.0
        self.on_road = False
        self.road = None               # (way, vertex we are moving from, direction)
        self.scale = 1.0               # Wheel speed x scale = true speed, learned from GPS.
        self.scale_samples = 0
        self.wheel_valid_seen = False
        self.last_gps_speed = None     # km/h, for coasting through brief dropouts.
        self.last_step = None
        self.saved = None
        self.stopping = False
        if self.path and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                lat, lon, track, scale = (float(data[k]) for k in ('lat', 'lon', 'track', 'scale'))
                if -90 <= lat <= 90 and -180 <= lon <= 180 and SCALE_LIMITS[0] <= scale <= SCALE_LIMITS[1]:
                    self.position, self.track, self.scale, self.source = (lat, lon), track % 360, scale, 'last-known'
                    self.scale_samples = int(data.get('samples', 0))
            except (OSError, ValueError, TypeError, KeyError):
                pass

    def load_roads(self):
        if self.roads is None:
            self.roads = False
            try:
                index = json.loads((self.map_dir / 'index.json').read_text(encoding='utf-8'))
                self.roads = RoadMap(json.loads((self.map_dir / f"{index[0]['name']}.json").read_text(encoding='utf-8')))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                pass
        return self.roads or None

    def wheel_speed(self, state):
        """Calibrated wheel speed in km/h from the sensor gateway, or None when unknown."""
        sample = state.samples.get(('vehicle.speed_kph', 0x500))
        if not sample or not state.connected or state.clock() - sample['seen'] > .5:
            return None, None
        if sample['quality'] == 'live':
            self.wheel_valid_seen = True
            return sample['value'], sample['value'] * self.scale
        # No pulses: stopped, once the sensor has been seen working in this run.
        return (0., 0.) if self.wheel_valid_seen else (None, None)

    def advance(self, metres):
        """Move along the road when on one, else straight ahead on the last heading."""
        roads = self.load_roads()
        if self.road is None and roads:
            snapped = roads.snap(self.position, self.track)
            if snapped:
                self.road, self.position = snapped[:3], snapped[3]
        guard = 0
        while self.road and metres > 0 and guard < 200:
            guard += 1
            way, vertex, direction = self.road
            points = roads.ways[way]
            following = vertex + direction
            if not 0 <= following < len(points):
                onward = roads.onward(way, vertex, self.track)
                self.road = onward
                continue
            gap = distance_m(self.position, points[following])
            if gap > .01:
                self.track = bearing(self.position, points[following])
            if metres < gap:
                self.position = moved(self.position, self.track, metres)
                metres = 0
            else:
                metres -= gap
                self.position = points[following]
                self.road = (way, following, direction)
        self.on_road = self.road is not None
        if metres > 0:
            self.position = moved(self.position, self.track, metres)

    def step(self, state, values):
        """Fuse this instant's GPS values and wheel speed; return the signals to publish."""
        now = self.clock()
        dt = 0. if self.last_step is None else max(0., min(1., now - self.last_step))
        self.last_step = now
        live = lambda name: values[name]['value'] if values.get(name, {}).get('quality') == 'live' else None
        lat, lon, gps_track = live('gps.latitude'), live('gps.longitude'), live('gps.track_deg')
        gps_speed = live('vehicle.speed_kph') if state.gps and values.get('vehicle.speed_kph', {}).get('source') == 'gpsd' else None
        raw_wheel, wheel = self.wheel_speed(state)
        out, coasting = {}, False
        if gps_speed is not None:
            self.last_gps_speed = gps_speed
        if lat is not None and lon is not None:
            self.position, self.source, self.fixed_this_run = (lat, lon), 'gps', True
            self.since_fix_m = self.since_fix_s = 0.
            self.road, self.on_road = None, False
            if gps_track is not None and (gps_speed is None or gps_speed > 3):
                self.track = gps_track % 360  # Course is noise when stopped; hold the last one.
            if gps_speed is not None and gps_speed >= CAL_MIN_KPH and raw_wheel and raw_wheel >= CAL_MIN_KPH * .6:
                ratio = gps_speed / raw_wheel
                if SCALE_LIMITS[0] <= ratio <= SCALE_LIMITS[1]:
                    gain = .2 if self.scale_samples < 20 else .01  # Learn quickly at first, then slowly.
                    self.scale += (ratio - self.scale) * gain * min(1., dt * 5 or 1.)
                    self.scale_samples = min(self.scale_samples + 1, 1000000)
        elif self.position is not None:
            self.since_fix_s += dt
            if wheel is not None:
                step_m = wheel / 3.6 * dt
                if step_m > 0:
                    self.advance(step_m)
                    self.since_fix_m += step_m
                self.source = 'estimated' if self.fixed_this_run or self.since_fix_m > 0 else 'last-known'
            elif self.fixed_this_run and self.since_fix_s <= COAST_S and self.last_gps_speed is not None:
                # No wheel speed: assume the car keeps its speed for a few seconds, then stop guessing.
                coasting = True
                step_m = self.last_gps_speed / 3.6 * dt
                if step_m > 0:
                    self.advance(step_m)
                    self.since_fix_m += step_m
                self.source = 'estimated'
            else:
                self.source = 'last-known'
        if gps_speed is not None:
            self.speed_source = 'gps'
        elif wheel is not None:
            self.speed_source = 'wheel'
            if state.gps:  # The GPS owns the speed signal; fill its gap, labelled, instead of blanking.
                out['vehicle.speed_kph'] = self.signal(wheel, 'Wheel speed (GPS lost)')
        elif coasting:
            self.speed_source = 'held'
            out['vehicle.speed_kph'] = self.signal(self.last_gps_speed, 'GPS speed held (brief dropout)')
        else:
            self.speed_source = 'none'
        quality = {'gps': 'live', 'estimated': 'live', 'last-known': 'stale'}.get(self.source, 'unavailable')
        label = {'gps': 'gpsd', 'estimated': 'Dead reckoning (wheel speed + map)', 'last-known': 'Last known position'}.get(self.source, 'None')
        for name, value in (('nav.latitude', self.position[0] if self.position else None),
                            ('nav.longitude', self.position[1] if self.position else None),
                            ('nav.track_deg', self.track if self.position else None)):
            out[name] = self.signal(value, label, quality if value is not None else 'unavailable')
        out['nav.source'] = self.signal(self.source, 'Navigation')
        out['nav.speed_source'] = self.signal(self.speed_source, 'Navigation')
        out['nav.accuracy_m'] = self.signal(self.accuracy(), 'Navigation', 'live' if self.position else 'unavailable')
        out['nav.since_fix_s'] = self.signal(round(self.since_fix_s, 1), 'Navigation')
        out['nav.wheel_scale'] = self.signal(round(self.scale, 4), 'Navigation', 'live' if self.scale_samples else 'unavailable')
        return out

    def accuracy(self):
        """Rough uncertainty in metres: grows with distance, faster when not following a road."""
        if self.position is None:
            return None
        if self.source == 'gps':
            return 5.
        calibration = .03 if self.scale_samples >= 20 else .1
        return round(8 + self.since_fix_m * (calibration if self.on_road else .25) + (0 if self.fixed_this_run else 25), 1)

    def signal(self, value, source, quality='live'):
        return {'value': value, 'quality': quality if value is not None else 'unavailable', 'source': source,
                'source_id': None, 'timestamp_ms': int(self.wall() * 1000)}

    def snapshot(self):
        return {'source': self.source, 'speed_source': self.speed_source, 'on_road': self.on_road,
                'since_fix_m': round(self.since_fix_m), 'since_fix_s': round(self.since_fix_s),
                'accuracy_m': self.accuracy(), 'wheel_scale': round(self.scale, 4), 'calibrated': self.scale_samples >= 20,
                'map_loaded': bool(self.roads)}

    async def save(self):
        if not self.path or self.position is None:
            return
        data = {'lat': round(self.position[0], 6), 'lon': round(self.position[1], 6), 'track': round(self.track, 1),
                'scale': round(self.scale, 4), 'samples': self.scale_samples}
        if data != self.saved:
            try:
                await asyncio.to_thread(atomic_write, self.path, data)
                self.saved = data
            except OSError:
                pass

    async def run(self):
        """Keep the last position and the wheel calibration on disk."""
        while not self.stopping:
            for _ in range(200):
                if self.stopping:
                    break
                await asyncio.sleep(.1)
            await self.save()
        await self.save()
