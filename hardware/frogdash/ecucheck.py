"""Is the ECU talking? The setup wizard's connection test.

check() looks at the last few seconds of CAN frames and says, for the ECU chosen, whether
its broadcast is arriving and, if not, the most likely reason in plain words: no CAN
interface, a silent bus, bus errors, a bus speed that differs from the ECU's, 29-bit frames
for an 11-bit ECU (or the reverse), or frames that belong to another ECU (named, so the
wizard can offer it). When it is talking, a few live readings show it.

It is a pure function of what was heard, so the published preview runs it on the
simulated MicroSquirt frames (tools/update_preview.py) and shows the same messages.
"""

READINGS = (('ecu.rpm', 'RPM', '{:.0f}'), ('ecu.coolant_c', 'Coolant', '{:.0f} °C'), ('ecu.map_kpa', 'MAP', '{:.0f} kPa'),
            ('ecu.battery_v', 'Battery', '{:.1f} V'), ('ecu.throttle_pct', 'Throttle', '{:.0f} %'))
WIRING = 'CAN H to CAN H and CAN L to CAN L, a 120 ohm resistor at each end of the bus, and the ECU powered (key on).'


def speed(bitrate):
    return f'{bitrate // 1000} kbit/s' if bitrate < 1000000 else '1 Mbit/s'


def check(candidate, frames, bus_bitrate, connected, errors=0, others=(), owned=()):
    """candidate: the ECU profile chosen (ecu.Profile). frames: [(id, extended, data)] heard
    in the last few seconds. bus_bitrate: the speed the dash's CAN bus runs at now.
    connected: the CAN interface is up. errors: error frames in that time. others: the other
    built-in profiles, to recognise another ECU's broadcast. owned: [(first, last)] 11-bit
    ID ranges of the Frogdash modules this car has (protocol.OWNED): their frames are not
    the ECU's, even where an ECU's IDs could be the same (rusEFI's default 0x200)."""
    frames = [f for f in frames if f[1] or not any(a <= f[0] <= b for a, b in owned)]
    name = candidate.label
    hints = list(candidate.data.get('setup') or [])
    result = lambda state, message, **extra: {'state': state, 'ecu': candidate.id, 'message': message, 'hints': extra.pop('hints', hints), **extra}
    if not connected:
        return result('no_interface', 'The Pi\'s CAN interface is not up, so nothing can be heard yet.',
                      hints=['Check the CAN board page: the board, its crystal and interrupt pin.',
                             'After setting up a CAN board the Pi needs one restart.'])
    mine = [f for f in frames if f[1] == candidate.extended and candidate.key(f[0]) in candidate.frames]
    if mine:
        values = {}
        for can_id, _, data in mine:
            values.update(candidate.decode(can_id, data))
        shown = [f'{label} {fmt.format(values[key])}' for key, label, fmt in READINGS if isinstance(values.get(key), (int, float))]
        ids = len({candidate.key(f[0]) for f in mine})
        return result('ok', f'{name} is talking: {ids} of its messages heard.' + (f' {" · ".join(shown)}.' if shown else ''),
                      readings=shown, hints=[])
    if bus_bitrate != candidate.bitrate:
        return result('wrong_speed', f'{name} sends at {speed(candidate.bitrate)} and the dash\'s CAN bus runs at '
                      f'{speed(bus_bitrate)}, so they cannot hear each other yet. Apply the setup (it changes the bus '
                      'speed), and this test runs again.', hints=hints)
    if getattr(candidate, 'obd2', False):
        return result('silent', f'No answers to OBD-II requests yet. The car answers only when asked: once {name} is '
                      'applied, the dash asks (about 20 times a second). Then: key on, and the CAN from the dash on the OBD '
                      'port, pins 6 (high) and 14 (low).', hints=hints)
    if not frames:
        if errors:
            return result('errors', f'The bus shows errors and no messages: usually CAN H and CAN L swapped, a missing '
                          f'120 ohm resistor, or a speed other than {speed(bus_bitrate)}.', hints=[WIRING, *hints])
        return result('silent', f'Nothing is arriving on the CAN bus. Check that {name}\'s CAN output is on and the wiring.',
                      hints=[*hints, WIRING])
    for other in others:
        found = [f for f in frames if f[1] == other.extended and other.key(f[0]) in other.frames]
        if other.id != candidate.id and len({other.key(f[0]) for f in found}) >= 2:
            return result('other_ecu', f'Messages are arriving, but they look like {other.label}, not {name}.',
                          suggest=other.id, suggest_label=other.label, hints=[])
    extended = sum(1 for f in frames if f[1])
    if candidate.extended and extended == 0:
        return result('wrong_ids', f'Messages are arriving, all with 11-bit IDs; {name} sends 29-bit IDs. Is another '
                      'device on the bus, and is the ECU\'s CAN output on?', hints=hints)
    if not candidate.extended and extended == len(frames):
        return result('wrong_ids', f'Messages are arriving, all with 29-bit IDs; {name} sends 11-bit IDs. Check that '
                      'the ECU\'s dash broadcast (not its tuning protocol) is on.', hints=hints)
    if candidate.base is not None:
        hints = [f'{name}\'s broadcast starts at 0x{candidate.base:03X} here; if it was moved in the ECU, set the '
                 'same first ID on this page.', *hints]
    return result('not_this_ecu', f'{len({f[0] for f in frames})} CAN IDs are on the bus, but none is {name}\'s. '
                  'Is its CAN output (dash broadcast) on?', hints=hints)
