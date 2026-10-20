"""Linux SocketCAN reception, optional GPS broadcast, and candump replay."""
import asyncio
import errno
import re
import socket
import struct

CAN_FRAME = struct.Struct("=IB3x8s")
LINE = re.compile(r"^\((\d+(?:\.\d+)?)\)\s+\S+\s+([0-9a-fA-F]{3}|[0-9a-fA-F]{8})#([0-9a-fA-F]{0,16})$")


def unpack_frame(packet):
    if len(packet) != CAN_FRAME.size:
        raise ValueError("not a classical CAN frame")
    flags, dlc, data = CAN_FRAME.unpack(packet)
    if dlc > 8:
        raise ValueError("invalid classical CAN DLC")
    return flags & 0x1FFFFFFF, data[:dlc], bool(flags & 0x80000000), bool(flags & 0x40000000), bool(flags & 0x20000000)


async def send_frame(send, packet, state, sleep=asyncio.sleep):
    """Send one frame, waiting while the CAN controller's send queue is full.

    Linux answers ENOBUFS at once when can0's queue (ten frames) is full: the dash is
    sending faster than the MCP2515 puts frames on the bus, as a firmware update does.
    That is a moment to wait, not a failure (October 2026: a taillight update stopped on
    "No buffer space available"). The caller's time limit still ends a bus that takes
    nothing at all (no other module acknowledging)."""
    pause = .001
    while True:
        try:
            await send(packet)
            return
        except OSError as exc:
            if exc.errno != errno.ENOBUFS:
                raise
        state.tx_full += 1
        await sleep(pause)
        pause = min(pause * 2, .02)


async def socketcan(state, interface):
    if not hasattr(socket, "AF_CAN"):
        state.status = "SocketCAN requires Linux; use --replay for desktop development"
        return
    loop = asyncio.get_running_loop()
    while True:
        try:
            with socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as bus:
                # Receive CAN error frames for diagnostics.
                bus.setsockopt(socket.SOL_CAN_RAW, 2, struct.pack("=I", 0x1FFFFFFF))
                bus.setblocking(False)
                bus.bind((interface,))
                state.connected, state.status = True, f"listening on {interface}"
                tx_lock = asyncio.Lock()
                async def send_control(identifier, data, wait=True):
                    """Commands and firmware frames wait for room in the queue (wait); the
                    dash's own broadcasts, sent from this reading loop, never do: a bus with
                    nobody acknowledging keeps the queue full, and reading must go on."""
                    packet = CAN_FRAME.pack(identifier, len(data), data)
                    async def transmit():
                        async with tx_lock:
                            if wait:
                                await send_frame(lambda frame: loop.sock_sendall(bus, frame), packet, state)
                            else:
                                await loop.sock_sendall(bus, packet)
                    await asyncio.wait_for(transmit(), .5)
                state.controls.attach(send_control)
                # Listen before transmitting to detect the CCM's existing GPS
                # publisher. RAW_RECV_OWN_MSGS stays disabled on this socket.
                next_tx = loop.time() + 2
                while True:
                    gps, now = state.gps, loop.time()
                    if gps and gps.transmit and not gps.conflict and now >= next_tx:
                        next_tx = now + .5
                        # A full TX queue (no node ACKing) must not drop reception.
                        try:
                            await send_control(0x203, gps.frame(), wait=False)
                        except (ValueError, TypeError, OverflowError) as exc:   # A value out of the frame's range
                            state.fault('GPS frame 0x203', exc)
                        except OSError as exc:  # Includes TimeoutError and ENOBUFS.
                            gps.tx_status = f"0x203 not sent: {exc or 'TX timeout'} (no other node ACKing?)"
                        else:
                            gps.tx_count += 1
                            gps.tx_status = "broadcasting 0x203 at 2 Hz"
                    runtime = state.runtime
                    if runtime and runtime.due(now):
                        try:
                            await send_control(0x309, runtime.frame(), wait=False)
                        except (ValueError, TypeError, OverflowError) as exc:
                            state.fault('engine runtime frame 0x309', exc)
                        except OSError as exc:
                            runtime.sent(False, exc)
                        else:
                            runtime.sent(True)
                    try:
                        packet = await asyncio.wait_for(loop.sock_recv(bus, CAN_FRAME.size), .1)
                    except TimeoutError:
                        continue
                    try:
                        frame = unpack_frame(packet)
                        if gps and gps.transmit and frame[0] == 0x203 and not any(frame[2:]):
                            gps.conflict = True
                            gps.tx_status = "BLOCKED: another 0x203 sender; disable CCM GPS TX and restart Frogdash"
                        if state.runtime:
                            state.runtime.observe(frame[0])
                        state.ingest(*frame)
                    except ValueError:
                        state.malformed += 1
                    except Exception as exc:   # Never let one frame stop the reader: every gauge depends on it.
                        state.malformed += 1
                        state.fault(f'CAN frame 0x{packet[:4].hex()}', exc)
        except OSError as exc:
            state.connected, state.status = False, f"{interface}: {exc}"
            state.controls.detach()
            await asyncio.sleep(1)
        finally:
            state.connected = False
            if state.runtime:
                state.runtime.reset()
            state.controls.detach()
            if state.gps and state.gps.transmit and not state.gps.conflict:
                state.gps.tx_status = "CAN disconnected"


def read_replay(path):
    frames, previous = [], None
    with open(path, encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = LINE.fullmatch(line)
            if not match:
                raise ValueError(f"{path}:{number}: expected candump -L classical data frame")
            stamp, identifier, payload = match.groups()
            stamp = float(stamp)
            if previous is not None and stamp < previous:
                raise ValueError(f"{path}:{number}: timestamps must not go backwards")
            data = bytes.fromhex(payload)
            can_id = int(identifier, 16)
            if can_id > (0x1FFFFFFF if len(identifier) == 8 else 0x7FF):
                raise ValueError(f"{path}:{number}: CAN identifier out of range")
            frames.append((stamp, can_id, data, len(identifier) == 8))
            previous = stamp
    if not frames:
        raise ValueError("replay contains no frames")
    return frames


async def replay(state, frames, repeat=False):
    try:
        while True:
            state.connected, state.status = True, "REPLAY — recorded data"
            start = asyncio.get_running_loop().time()
            for stamp, can_id, data, extended in frames:
                delay = start + stamp - frames[0][0] - asyncio.get_running_loop().time()
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    state.ingest(can_id, data, extended)
                except Exception as exc:   # One odd recorded frame must not end the replay
                    state.malformed += 1
                    state.fault(f'replayed frame 0x{can_id:03X}', exc)
            if not repeat:
                state.status = "replay complete"
                return
            await asyncio.sleep(.05)
    finally:
        state.connected = False
