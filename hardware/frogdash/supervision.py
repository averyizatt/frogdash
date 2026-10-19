"""Systemd event-loop watchdog, and the supervisor that keeps background loops running.
Independent of power/shutdown handling."""
import asyncio
import os
import socket


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if not address or os.name != 'posix':
        return
    if address.startswith('@'):
        address = '\0' + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), address)
    except OSError:
        pass


async def keep_running(state, name, start, owner=None):
    """Run a background loop for the life of the dash. If it fails, the error is recorded
    (state.fault: the event log shows it) and the loop is started again after a pause,
    1 s doubling to 30 s, so one unexpected value cannot switch a feature off for the rest
    of the drive. A loop that ends by itself (stopping) is not started again."""
    pause = 1.0
    while True:
        try:
            await start()
            return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            state.fault(name, error)
        for _ in range(int(pause * 10)):
            if owner is not None and getattr(owner, 'stopping', False):
                break   # Shutting down: start it once more so it can finish and save.
            await asyncio.sleep(.1)
        pause = min(pause * 2, 30)


def supervise(state, name, start, owner=None):
    return asyncio.create_task(keep_running(state, name, start, owner))


async def watchdog():
    notify('READY=1')
    while True:
        notify('WATCHDOG=1')
        await asyncio.sleep(2)
