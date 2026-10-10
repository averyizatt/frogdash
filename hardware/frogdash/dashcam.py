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

Starting live view takes several seconds (the camera's web server, RTSP, then ffmpeg's
first picture), far too long for a reverse view. So by default the stream is kept
running in the background, on the rear camera, and a view shows the picture that is
already arriving. The camera keeps recording to its own card throughout.
"""
import asyncio
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
STALL_S = 8.0         # No new picture for this long while buffering: reconnect.
START_GRACE_S = 20.0  # Allowed for the first picture after a start.
PARK_S = 3.0          # After the last viewer leaves, return to the rear camera.
RETRY_MAX_S = 30.0


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

    def __init__(self, host='192.168.169.1', width=1280, fps=15, quality='high', idle_s=10.0, opener=open_dashcam, get=camera_get,
                 settings=None, keep_warm=False, **kwargs):
        super().__init__(width, 720, fps, 0, idle_s=idle_s, opener=opener, quality=quality, **kwargs)
        self.host, self.side, self.get = host, 'front', get
        self.settings = settings      # Path of dashcam.json; the owner's choice survives restarts.
        self.keep_warm = keep_warm    # Buffer in the background so a view is instant.
        self.held = None              # Why the camera may not be used right now, or None.
        self.started_at = None
        self._park = None
        if settings:
            try:
                saved = json.loads(settings.read_text(encoding='utf-8'))
                if isinstance(saved, dict) and isinstance(saved.get('keep_warm'), bool):
                    self.keep_warm = saved['keep_warm']
            except (OSError, ValueError):
                pass

    def status(self):
        return {**super().status(), 'host': self.host, 'side': self.side, 'keep_warm': self.keep_warm, 'held': self.held}

    def set_keep_warm(self, enabled):
        self.keep_warm = bool(enabled)
        if self.settings:
            try:
                self.settings.write_text(json.dumps({'keep_warm': self.keep_warm}), encoding='utf-8')
            except OSError:
                pass

    def hold(self, reason):
        """The camera's Wi-Fi is in use for something else (the phone hotspot): stop and do not retry."""
        self.held = reason or None

    async def start(self):
        if self.held:
            self.error = self.held
            raise RuntimeError(self.held)
        if self.keep_warm and not self.viewers:
            self.side = 'rear'  # Buffering exists for the reverse view.
        await super().start()
        self.started_at = self.clock()

    async def release(self):
        if not self.keep_warm:
            await super().release()
            return
        self.viewers = max(0, self.viewers - 1)
        if not self.viewers and self.side != 'rear' and not self._park:
            self._park = asyncio.create_task(self._park_later())

    async def _park_later(self):
        try:
            await asyncio.sleep(PARK_S)
        except asyncio.CancelledError:
            return
        self._park = None
        if not self.viewers and self.running and self.keep_warm and self.side != 'rear':
            try:
                await asyncio.to_thread(self.switch, 'rear')
            except (OSError, RuntimeError, ValueError):
                pass  # tend() restarts on the rear camera if the stream is lost.

    async def tend(self, delay=2.0):
        """One look at the background stream; returns the seconds until the next look."""
        if self.held:
            if self.running:
                await self.close()
            self.error = self.held
            return 2.0
        if self.running:
            if not self.keep_warm:
                if not self.viewers and not self._idle:   # Buffering was switched off: stop as an idle view would.
                    self._idle = asyncio.create_task(self._stop_later())
                return 2.0
            # Frozen or never started: the camera's Wi-Fi dropped, or its live view stalled.
            if self.frame_at is not None:
                stuck = self.clock() - self.frame_at > STALL_S
            else:
                stuck = self.clock() - (self.started_at or self.clock()) > START_GRACE_S
            if stuck:
                await self.close()
                self.error = 'Dash cam picture stopped: reconnecting'
                return 1.0
            return 2.0
        if not self.keep_warm:
            return 2.0
        try:
            await self.start()
            return 2.0
        except Exception:  # Camera off or out of range: try again, less and less often.
            return min(max(delay, 2.0) * 2, RETRY_MAX_S)

    async def run(self):
        delay = 1.0
        while True:
            await asyncio.sleep(delay)
            delay = await self.tend(delay)

    def ended_threadsafe(self):
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: loop.create_task(self.close()))

    def switch(self, side):
        """Front or rear; applied live when watching, otherwise on the next start."""
        if side not in SIDES:
            raise ValueError('side must be front or rear')
        if side == self.side and self.running:
            return  # Already showing it: the camera's web server is not bothered again.
        self.side = side
        if self.running:
            reply = self.get(self.host, f'/app/setparamvalue?param=switchcam&value={SIDES[side]}')
            if reply.get('result') != 0:
                raise RuntimeError(f'Dash cam did not switch: {reply}')
