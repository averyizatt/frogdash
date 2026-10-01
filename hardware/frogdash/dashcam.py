"""Optional Wi-Fi dash cam view (Viidure-app cameras such as Wanlipo; eeasytech/HUAXIN).

Live view copies what the Viidure phone app does, as captured from the app:

1. GET /app/setsystime and /app/enterrecorder on the camera's web server;
2. keep a TCP connection open on port 5000 (the camera's notification channel);
3. read standard RTSP from rtsp://<camera>:554/ over TCP (video only: the camera
   advertises an AAC audio track with an invalid configuration);
4. poll /app/getparamvalue?param=rec every few seconds while watching.

ffmpeg turns the video into JPEG frames, which reuse the reverse camera's MJPEG
stream, frame-age reporting and lost-feed handling. The camera's web server is
fragile, so only the app's own requests are sent, one at a time. Front/rear uses
/app/setparamvalue?param=switchcam. The camera reports no live GPS; its route is
stored in the recordings only.
"""
import json
import socket
import subprocess
import threading
import time
import urllib.request

from .camera import Camera

HEADERS = {'Connection': 'close', 'Accept-Encoding': '',
           'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 13; M2103K19G Build/TP1A.220624.014)'}
KEEPALIVE_S = 4.0
SIDES = {'front': 0, 'rear': 1}


def camera_get(host, path, timeout=4.0):
    """One GET to the camera's API; returns the decoded JSON reply."""
    request = urllib.request.Request(f'http://{host}{path}', headers={**HEADERS, 'Host': host})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(8192).decode('utf-8', 'replace')
    try:
        return json.loads(body)
    except ValueError:
        return {'result': None, 'raw': body[:200]}


def split_jpegs(buffer):
    """Split complete JPEG images off the front of a byte buffer; return (frames, rest).

    ffmpeg's MJPEG output has no embedded thumbnails and 0xFF bytes in the image data
    are stuffed, so FF D9 marks the end of each image.
    """
    frames = []
    while True:
        start = buffer.find(b'\xff\xd8')
        if start < 0:
            return frames, b''
        end = buffer.find(b'\xff\xd9', start + 2)
        if end < 0:
            return frames, buffer[start:]
        frames.append(buffer[start:end + 2])
        buffer = buffer[end + 2:]


def ffmpeg_command(url, width, fps, quality):
    q = {'medium': 7, 'high': 4, 'max': 2}[quality]
    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-rtsp_transport', 'tcp', '-timeout', '5000000', '-fflags', 'nobuffer', '-flags', 'low_delay',
            '-i', url, '-map', '0:v:0', '-an',
            '-vf', f"scale='min({width},iw)':-2", '-r', str(fps),
            '-c:v', 'mjpeg', '-q:v', str(q), '-f', 'image2pipe', '-']


def open_dashcam(camera, get=camera_get, popen=subprocess.Popen, connect=socket.create_connection):
    """Start live view on the dash cam; return a stop callable."""
    host = camera.host
    get(host, '/app/setsystime?date=' + time.strftime('%Y%m%d%H%M%S'))
    reply = get(host, '/app/enterrecorder')
    if reply.get('result') != 0:
        raise RuntimeError(f'Dash cam refused live view: {reply}')
    if camera.side != 'front':
        get(host, f'/app/setparamvalue?param=switchcam&value={SIDES[camera.side]}')
    notify = connect((host, 5000), timeout=4)
    process = popen(ffmpeg_command(f'rtsp://{host}:554/', camera.width, camera.fps, camera.quality),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    stopping = threading.Event()

    def read_frames():
        buffer = b''
        while not stopping.is_set():
            chunk = process.stdout.read(65536)
            if not chunk:
                break
            frames, buffer = split_jpegs(buffer + chunk)
            for frame in frames:
                camera.publish_threadsafe(frame)
            if len(buffer) > 4 * 1024 * 1024:
                buffer = b''  # Never grow without bound on a corrupt stream.
        if not stopping.is_set():
            error = process.stderr.read(400).decode('utf-8', 'replace').strip().splitlines()
            camera.error = 'Dash cam stream ended' + (f': {error[-1]}' if error else '')
            camera.ended_threadsafe()  # Close so the next view starts live mode again.

    def keep_alive():
        notify.settimeout(.5)
        next_poll = time.monotonic() + KEEPALIVE_S
        while not stopping.is_set():
            try:
                notify.recv(1024)  # Camera notifications ({"msgid":"rec",...}); drained and ignored.
            except OSError:
                pass
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + KEEPALIVE_S
                try:
                    get(host, '/app/getparamvalue?param=rec')
                except OSError:
                    pass

    threads = [threading.Thread(target=read_frames, daemon=True), threading.Thread(target=keep_alive, daemon=True)]
    for thread in threads:
        thread.start()

    def stop():
        stopping.set()
        process.terminate()
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()
        notify.close()
        for thread in threads:
            thread.join(2)
    return stop


class Dashcam(Camera):
    """The reverse camera's stream plumbing with a Wi-Fi dash cam as the source."""

    def __init__(self, host='192.168.169.1', width=1280, fps=15, quality='high', idle_s=10.0, opener=open_dashcam, get=camera_get, **kwargs):
        super().__init__(width, 720, fps, 0, idle_s=idle_s, opener=opener, quality=quality, **kwargs)
        self.host, self.side, self.get = host, 'front', get

    def status(self):
        return {**super().status(), 'host': self.host, 'side': self.side}

    def ended_threadsafe(self):
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: loop.create_task(self.close()))

    def switch(self, side):
        """Front or rear; applied live when watching, otherwise on the next start."""
        if side not in SIDES:
            raise ValueError('side must be front or rear')
        self.side = side
        if self.running:
            reply = self.get(self.host, f'/app/setparamvalue?param=switchcam&value={SIDES[side]}')
            if reply.get('result') != 0:
                raise RuntimeError(f'Dash cam did not switch: {reply}')
