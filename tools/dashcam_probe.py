"""Gently probe a Viidure-app Wi-Fi dash cam (Wanlipo, eeasytech/HUAXIN) for live video.

Connect to the dash cam's Wi-Fi first (camera at 192.168.169.1), close the phone app,
then run:

    python3 tools/dashcam_probe.py

The camera's small web server is fragile: bursts of unknown requests can stop it
answering until the camera is power-cycled. This probe therefore sends only the
requests the Viidure app itself makes, one at a time with pauses and the app's
headers, then one RTSP handshake on the reported port and a short ffprobe. Nothing
on the camera is changed. The report is printed and saved to dashcam-probe.json.
"""
import argparse
import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

HEADERS = {'Connection': 'close', 'Accept-Encoding': '',
           'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 13; M2103K19G Build/TP1A.220624.014)'}
PAUSE = 1.5


def get(host, path, timeout=4):
    try:
        request = urllib.request.Request(f'http://{host}{path}', headers={**HEADERS, 'Host': host})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {'status': response.status, 'body': response.read(4096).decode('utf-8', 'replace')}
    except urllib.error.HTTPError as exc:
        return {'status': exc.code}
    except (OSError, ValueError) as exc:
        return {'error': f'{type(exc).__name__}: {exc}'[:120]}


def rtsp_handshake(host, port, path=''):
    """One OPTIONS and DESCRIBE exchange; shows whether the port really speaks RTSP."""
    url = f'rtsp://{host}:{port}{path}'
    replies = {}
    try:
        with socket.create_connection((host, port), timeout=4) as conn:
            conn.settimeout(4)
            for seq, method in enumerate(('OPTIONS', 'DESCRIBE'), 1):  # one request each, short timeouts
                extra = 'Accept: application/sdp\r\n' if method == 'DESCRIBE' else ''
                conn.sendall(f'{method} {url} RTSP/1.0\r\nCSeq: {seq}\r\nUser-Agent: Viidure\r\n{extra}\r\n'.encode())
                time.sleep(.5)
                try:
                    replies[method] = conn.recv(2048).decode('utf-8', 'replace')
                except socket.timeout:
                    replies[method] = '(no reply)'
    except OSError as exc:
        replies['error'] = f'{type(exc).__name__}: {exc}'
    return url, replies


def ffprobe(url):
    if not shutil.which('ffprobe'):
        return 'ffprobe not installed (sudo apt install ffmpeg)'
    try:
        out = subprocess.run(['ffprobe', '-v', 'error', '-rtsp_transport', 'tcp', '-timeout', '5000000',
                              '-show_entries', 'stream=codec_name,width,height,avg_frame_rate', '-of', 'json', url],
                             capture_output=True, text=True, timeout=15)
        streams = json.loads(out.stdout or '{}').get('streams') if out.returncode == 0 else None
        return streams or (out.stderr.strip().splitlines() or ['failed'])[-1][:200]
    except (subprocess.TimeoutExpired, ValueError) as exc:
        return type(exc).__name__


def live(host):
    """Copy the Viidure app's live-view sequence, then probe the RTSP stream on port 554."""
    stamp = time.strftime('%Y%m%d%H%M%S')
    for path in ('/app/getproductinfo', f'/app/setsystime?date={stamp}', '/app/getdeviceattr', '/app/enterrecorder'):
        result = get(host, path)
        print(f'GET {path} -> {result.get("status", result.get("error"))} {result.get("body", "")[:200]}')
        if 'error' in result:
            print('Camera web server is not answering: power-cycle the camera and reconnect (sudo nmcli con up dashcam).')
            return
        time.sleep(.5)
    # The app keeps a notification connection on port 5000 open while watching.
    try:
        notify = socket.create_connection((host, 5000), timeout=4)
    except OSError as exc:
        print(f'port 5000 refused ({exc}); trying video anyway')
        notify = socket.socket()
    notify.settimeout(2)
    try:
        time.sleep(1.5)
        try:
            print('port 5000 says:', notify.recv(512).decode('utf-8', 'replace').strip()[:200])
        except OSError:
            print('port 5000: connected (no message yet)')
        for path in ('/', '/live', '/live/tcp/ch1', '/stream0', '/front'):
            url, replies = rtsp_handshake(host, 554, path)
            print(f'\n{url}')
            for method, text in replies.items():
                print(f'  {method}: ' + text.strip().replace('\r\n', ' | ')[:300])
            if 'RTSP/1.0 200' in replies.get('DESCRIBE', ''):
                print('  ffprobe:', ffprobe(url))
                break
            get(host, '/app/getparamvalue?param=rec')  # The app's keep-alive poll.
    finally:
        notify.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', default='192.168.169.1')
    parser.add_argument('--live', action='store_true', help="Copy the app's live-view sequence and probe the RTSP video")
    args = parser.parse_args()
    if args.live:
        return live(args.host)
    host, report = args.host, {}
    for path in ('/app/getproductinfo', '/app/getdeviceattr', '/app/getsdinfo', '/app/getmediainfo'):
        report[path] = result = get(host, path)
        print(f'GET {path} -> {result.get("status", result.get("error"))} {result.get("body", "")[:300]}')
        time.sleep(PAUSE)
    # The app retries media info while the camera finishes switching to app mode.
    media = {}
    for attempt in range(4):
        try:
            media = json.loads(report['/app/getmediainfo'].get('body', '{}').replace('result:', '"result":'))
        except ValueError:
            media = {}
        if media.get('result') == 0:
            break
        time.sleep(3)
        report['/app/getmediainfo'] = result = get(host, '/app/getmediainfo')
        print(f'GET /app/getmediainfo (retry {attempt + 1}) -> {result.get("status", result.get("error"))} {result.get("body", "")[:300]}')
    info = media.get('info') or {}
    port = int(info.get('port') or 5000)
    base = (info.get('rtsp') or f'rtsp://{host}').rstrip('/')
    report['rtsp'] = {}
    for path in ('', '/', '/live', '/stream'):
        url, replies = rtsp_handshake(host, port, path)
        print(f'\n{url} handshake:')
        for method, text in replies.items():
            print(f'  {method}: ' + text.strip().replace('\r\n', ' | ')[:400])
        report['rtsp'][url] = {'handshake': replies}
        time.sleep(PAUSE)
        if 'RTSP/1.0 200' in replies.get('DESCRIBE', ''):
            report['rtsp'][url]['ffprobe'] = probe = ffprobe(f'{base}:{port}{path}')
            print(f'  ffprobe: {probe}')
            break
    with open('dashcam-probe.json', 'w', encoding='utf-8') as out:
        json.dump(report, out, indent=1)
    print('\nSaved dashcam-probe.json')


if __name__ == '__main__':
    main()
