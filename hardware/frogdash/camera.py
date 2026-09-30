"""Optional reverse camera: a Raspberry Pi CSI camera served as a local MJPEG stream.

The camera runs only while a dashboard view is watching (plus a short warm hold),
never touches CAN, and reports frame age so the display can show a frozen or
missing feed as lost instead of presenting an old image as live.
"""
import asyncio
import io
import time
from collections import deque

BOUNDARY = 'frogdashframe'


def open_picamera2(camera):
    """Start hardware MJPEG capture on the first CSI camera; return a stop callable.

    Uses the Raspberry Pi OS python3-picamera2 package (the service venv is built
    with --system-site-packages). Imported lazily so other platforms still run.
    """
    from libcamera import Transform
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder, Quality
    from picamera2.outputs import FileOutput

    class Sink(io.BufferedIOBase):
        def writable(self):
            return True

        def write(self, data):
            camera.publish_threadsafe(bytes(data))
            return len(data)

    picam = Picamera2()
    try:
        flip = camera.rotate == 180
        config = picam.create_video_configuration(
            main={'size': (camera.width, camera.height)}, transform=Transform(hflip=flip, vflip=flip),
            controls={'FrameRate': camera.fps})
        picam.configure(config)
        quality = {'medium': Quality.MEDIUM, 'high': Quality.HIGH, 'max': Quality.VERY_HIGH}[camera.quality]
        picam.start_recording(MJPEGEncoder(), FileOutput(Sink()), quality=quality)
    except Exception:
        picam.close()
        raise

    def stop():
        try:
            picam.stop_recording()
        finally:
            picam.close()
    return stop


class Camera:
    def __init__(self, width=1024, height=768, fps=30, rotate=0, idle_s=20.0, opener=open_picamera2, clock=time.monotonic, quality='high'):
        if width not in range(160, 1921) or height not in range(120, 1081) or not 5 <= fps <= 60 or rotate not in (0, 180) or quality not in ('medium', 'high', 'max'):
            raise ValueError('Camera size must be 160x120 to 1920x1080, 5-60 fps, rotation 0 or 180, quality medium/high/max')
        self.width, self.height, self.fps, self.rotate, self.idle_s, self.quality = width, height, fps, rotate, idle_s, quality
        self.opener, self.clock = opener, clock
        self.frame = None
        self.frame_at = None
        self.sequence = 0
        self.times = deque(maxlen=31)
        self.error = None
        self.viewers = 0
        self._stop = None
        self._loop = None
        self._changed = None
        self._idle = None
        self._lock = asyncio.Lock()

    @property
    def running(self):
        return self._stop is not None

    def status(self):
        now = self.clock()
        span = self.times[-1] - self.times[0] if len(self.times) > 1 else 0
        return {'enabled': True, 'running': self.running, 'viewers': self.viewers, 'error': self.error,
                'width': self.width, 'height': self.height, 'rotate': self.rotate, 'quality': self.quality,
                'frame_age_ms': None if self.frame_at is None else round((now - self.frame_at) * 1000),
                'fps': round((len(self.times) - 1) / span, 1) if span > 0 else 0.0}

    def publish_threadsafe(self, data):
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self.publish, data)

    def publish(self, data):
        if not data.startswith(b'\xff\xd8'):
            return
        self.frame, self.frame_at = data, self.clock()
        self.times.append(self.frame_at)
        self.sequence += 1
        changed, self._changed = self._changed, asyncio.Event()
        if changed:
            changed.set()

    async def acquire(self):
        self.viewers += 1
        if self._idle:
            self._idle.cancel()
            self._idle = None
        async with self._lock:
            if self.running:
                return
            self._loop = asyncio.get_running_loop()
            self._changed = asyncio.Event()
            self.frame = self.frame_at = None
            self.times.clear()
            try:
                self._stop = await asyncio.to_thread(self.opener, self)
                self.error = None
            except Exception as exc:  # Missing camera, busy device or absent picamera2.
                self.viewers -= 1
                self.error = f'{type(exc).__name__}: {exc}'[:200]
                raise

    async def release(self):
        self.viewers = max(0, self.viewers - 1)
        if not self.viewers and self.running and not self._idle:
            self._idle = asyncio.create_task(self._stop_later())

    async def _stop_later(self):
        try:
            await asyncio.sleep(self.idle_s)
        except asyncio.CancelledError:
            return
        self._idle = None
        await self.close()

    async def close(self):
        async with self._lock:
            stop, self._stop = self._stop, None
            if stop:
                try:
                    await asyncio.to_thread(stop)
                except Exception as exc:
                    self.error = f'{type(exc).__name__}: {exc}'[:200]

    async def next_frame(self, after, timeout=1.0):
        """Return (sequence, jpeg) newer than `after`, or None if none arrives in time."""
        if self.sequence > after and self.frame:
            return self.sequence, self.frame
        changed = self._changed
        if changed is None:
            return None
        try:
            await asyncio.wait_for(changed.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        return (self.sequence, self.frame) if self.sequence > after and self.frame else None
