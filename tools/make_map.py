"""Build a compact offline street map for the dash from OpenStreetMap data.

    python tools/make_map.py grand-junction 39.00 -108.72 39.15 -108.40 "Grand Junction, CO"
    python tools/make_map.py grand-junction ... --from-file overpass.json   # reuse a download

Downloads roads, rivers and railways for the bounding box (south west north east) from
the Overpass API and writes hardware/maps/<name>.json: ways as delta-encoded integer
coordinates (1e-5 degree, about 1 m) with a road class and street name. The dash draws
them itself, so no map image tiles are needed. Data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSES = {'motorway': 0, 'trunk': 0, 'motorway_link': 0, 'trunk_link': 0,
           'primary': 1, 'primary_link': 1,
           'secondary': 2, 'tertiary': 2, 'secondary_link': 2, 'tertiary_link': 2,
           'residential': 3, 'unclassified': 3, 'living_street': 3,
           'service': 4, 'track': 4}
RIVER, RAIL = 5, 6
SCALE = 100000


def download(south, west, north, east):
    box = f'({south},{west},{north},{east})'
    query = f'[out:json][timeout:150];(way["highway"]{box};way["waterway"="river"]{box};way["railway"="rail"]{box};);out tags geom qt;'
    request = urllib.request.Request('https://overpass-api.de/api/interpreter', data=urllib.parse.urlencode({'data': query}).encode(),
                                     headers={'User-Agent': 'frogdash-map/1.0'})
    with urllib.request.urlopen(request, timeout=200) as response:
        return json.load(response)


def build(data, bounds, title):
    south, west, north, east = bounds
    names, index, ways = [], {}, []
    for element in data['elements']:
        tags, geometry = element.get('tags', {}), element.get('geometry')
        if element.get('type') != 'way' or not geometry or len(geometry) < 2:
            continue
        kind = CLASSES.get(tags.get('highway'))
        if kind is None:
            kind = RIVER if tags.get('waterway') == 'river' else RAIL if tags.get('railway') == 'rail' else None
        if kind is None or tags.get('access') == 'private' and kind == 4:
            continue
        if kind == 4 and tags.get('service') in ('parking_aisle', 'driveway'):
            continue  # Parking rows and driveways clutter the map and double its size.
        name = tags.get('name') or tags.get('ref') or ''
        if name not in index:
            index[name] = len(names)
            names.append(name)
        points, previous = [], (round(south * SCALE), round(west * SCALE))
        last = None
        for point in geometry:
            current = (round(point['lat'] * SCALE), round(point['lon'] * SCALE))
            if current == last:
                continue
            points += [current[0] - previous[0], current[1] - previous[1]]
            previous = last = current
        if len(points) >= 4:
            ways.append([kind, index[name], points])
    ways.sort(key=lambda way: -way[0])  # Minor roads first so major roads draw on top.
    return {'title': title, 'bounds': [south, west, north, east], 'scale': SCALE, 'names': names, 'ways': ways,
            'attribution': '© OpenStreetMap contributors (ODbL)'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('name')
    parser.add_argument('south', type=float); parser.add_argument('west', type=float)
    parser.add_argument('north', type=float); parser.add_argument('east', type=float)
    parser.add_argument('title')
    parser.add_argument('--from-file', type=Path, help='Existing Overpass JSON instead of downloading')
    args = parser.parse_args()
    bounds = (args.south, args.west, args.north, args.east)
    data = json.loads(args.from_file.read_text(encoding='utf-8')) if args.from_file else download(*bounds)
    result = build(data, bounds, args.title)
    out = ROOT / 'hardware' / 'maps'
    out.mkdir(exist_ok=True)
    path = out / f'{args.name}.json'
    path.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    index = out / 'index.json'
    maps = json.loads(index.read_text(encoding='utf-8')) if index.exists() else []
    maps = [m for m in maps if m['name'] != args.name] + [{'name': args.name, 'title': args.title, 'bounds': list(bounds)}]
    index.write_text(json.dumps(maps, indent=1) + '\n', encoding='utf-8')
    print(f'{path}: {len(result["ways"])} ways, {len(result["names"])} names, {path.stat().st_size / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
