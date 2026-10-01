"""Probe a Wi-Fi dash cam (Viidure-app cameras such as Wanlipo) for live video and GPS.

Connect the Pi (or a laptop) to the dash cam's Wi-Fi first, then run:

    python3 tools/dashcam_probe.py                 # read-only probe
    python3 tools/dashcam_probe.py --live          # also ask the camera to start live view

It only sends HTTP GET requests (nothing is changed except, with --live, the camera's
live-view mode, the same thing the phone app does when you open it) and tests RTSP
URLs with ffprobe when installed (sudo apt install ffmpeg). The report is printed and
saved to dashcam-probe.json; send that file back for the dashboard integration.
"""
import argparse
import json
import shutil
import socket
import subprocess
import urllib.error
import urllib.request

HOSTS = ['192.168.169.1', '192.168.1.254', '192.168.0.1', '192.72.1.1', '192.168.42.1']
INFO = ['/app/getproductinfo', '/app/getdeviceattr', '/app/getmediainfo', '/app/getsdinfo',
        '/app/getrecduration', '/app/getparamitems?param=all', '/app/getparamvalue?param=all',
        '/app/capability']
GPS = ['/app/getgpsinfo', '/app/getgps', '/app/gpsinfo', '/app/getlocation', '/app/getgpsdata',
       '/app/getparamvalue?param=gps', '/app/getspeed']
LIVE = ['/app/enterrecorder', '/app/startlive', '/app/setparamvalue?param=switchcam&value=0']
NOVATEK = ['/?custom=1&cmd=3016', '/?custom=1&cmd=3012', '/?custom=1&cmd=3014']
RTSP_PATHS = ['', '/', '/live', '/live/tcp/ch1', '/liveRTSP/av1', '/xxx.mov', '/live/ch0', '/stream0', '/1', '/front', '/rear']
PORTS = [80, 554, 5000, 6035, 8080, 8192, 8554]


def get(url, timeout=3):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Viidure'}), timeout=timeout) as response:
            body = response.read(4096)
            return {'status': response.status, 'type': response.headers.get('Content-Type'), 'body': body.decode('utf-8', 'replace')}
    except urllib.error.HTTPError as exc:
        return {'status': exc.code}
    except (OSError, ValueError) as exc:
        return {'error': f'{type(exc).__name__}: {exc}'[:120]}


def port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def rtsp(url):
    if not shutil.which('ffprobe'):
        return {'skipped': 'ffprobe not installed (sudo apt install ffmpeg)'}
    result = {}
    for transport in ('tcp', 'udp'):
        try:
            out = subprocess.run(['ffprobe', '-v', 'error', '-rtsp_transport', transport, '-timeout', '4000000',
                                  '-show_entries', 'stream=codec_name,width,height,avg_frame_rate', '-of', 'json', url],
                                 capture_output=True, text=True, timeout=12)
            streams = json.loads(out.stdout or '{}').get('streams') if out.returncode == 0 else None
            result[transport] = streams or (out.stderr.strip().splitlines() or ['failed'])[-1][:160]
            if streams:
                break
        except (subprocess.TimeoutExpired, ValueError) as exc:
            result[transport] = f'{type(exc).__name__}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', help='Camera IP if known')
    parser.add_argument('--live', action='store_true', help='Ask the camera to enter live view first')
    args = parser.parse_args()
    report = {'hosts': {}}
    hosts = [args.host] if args.host else HOSTS
    for host in hosts:
        ports = {port: port_open(host, port) for port in PORTS}
        if not any(ports.values()):
            report['hosts'][host] = 'no open ports'
            continue
        print(f'== {host}: open ports {[p for p, ok in ports.items() if ok]}')
        entry = report['hosts'][host] = {'ports': ports, 'http': {}, 'rtsp': {}}
        if ports[80]:
            for path in INFO + GPS + NOVATEK + (LIVE if args.live else []):
                entry['http'][path] = result = get(f'http://{host}{path}')
                print(f'  GET {path} -> {result.get("status", result.get("error"))} {str(result.get("body", ""))[:100]!r}')
        for port in (p for p in (554, 5000, 8554, 6035) if ports[p]):
            for path in RTSP_PATHS:
                url = f'rtsp://{host}:{port}{path}'
                entry['rtsp'][url] = result = rtsp(url)
                print(f'  {url} -> {result}')
                if any(isinstance(v, list) for v in result.values()):
                    break  # One working URL per port is enough.
    with open('dashcam-probe.json', 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1)
    print('\nSaved dashcam-probe.json')


if __name__ == '__main__':
    main()
