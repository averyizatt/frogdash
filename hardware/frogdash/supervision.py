"""Systemd event-loop watchdog; independent of power/shutdown handling."""
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


async def watchdog():
    notify('READY=1')
    while True:
        notify('WATCHDOG=1')
        await asyncio.sleep(2)
