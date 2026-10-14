#!/usr/bin/env python3
"""The dash screen's mode: exactly 1920 x 720, tried safely first. Run as root.

The 1920 x 720 panel's own EDID offers a list of other modes (or cannot be read at all),
so the Pi picks one, the panel scales it, and every mode change on the way up (firmware,
kernel, kiosk) makes the panel search for its signal again. Here the Pi is given an EDID
that offers exactly one mode, 1920 x 720 at 60 Hz: the panel's own timing for it when its
EDID has one, else the standard reduced-blanking timing.

A wrong mode would leave a dark screen and there is no SSH, so it is tried first: the Pi
restarts once in the bootloader's one-time trial ("tryboot"), where only the [tryboot]
section of config.txt points at the trial command line. The dash then asks whether the
picture is right. KEEP makes it permanent; no answer within 90 s restarts the Pi
normally, which is the old setup, untouched.

  frogdash_screen.py survey     record what the Pi sees in screen-status.json
  frogdash_screen.py install    put the EDID files in place and the boot speed-ups (setup)
  frogdash_screen.py boot       after every start: finish or undo a trial, then survey
  frogdash_screen.py            act on screen-request: trial, keep, revert (path unit)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

STATE = Path(os.environ.get('FROGDASH_STATE') or os.path.realpath('/var/lib/frogdash'))
REQUEST, STATUS, TRIAL = STATE / 'screen-request', STATE / 'screen-status.json', STATE / 'screen-trial.json'
DRM = Path(os.environ.get('FROGDASH_DRM', '/sys/class/drm'))
FIRMWARE = Path(os.environ.get('FROGDASH_FIRMWARE', '/lib/firmware'))
PROC = Path(os.environ.get('FROGDASH_PROC', '/proc'))
TRYBOOT_FLAG = PROC / 'device-tree/chosen/bootloader/tryboot'
EDID_NAME = 'frogdash-1920x720.bin'
OUR_MAKER = bytes.fromhex('19f8')   # "FOX": tells our own EDID from the panel's
TRIAL_CMDLINE = 'frogdash-cmdline-trial.txt'
TRYBOOT_MARK = '# Written by the dash for a screen trial (tools/frogdash_screen.py); removed after it.'
KEEP_WINDOW_S = 90   # A cold start can take half a minute to show the dash

# --------------------------------------------------------------------------- EDID


def checksum_ok(block):
    return len(block) == 128 and sum(block) % 256 == 0


def edid_ok(edid):
    return (len(edid) >= 128 and len(edid) % 128 == 0 and edid[:8] == bytes.fromhex('00ffffffffffff00')
            and all(checksum_ok(edid[i:i + 128]) for i in range(0, len(edid), 128)))


def parse_dtd(d):
    """An 18-byte detailed timing descriptor, or None for a display descriptor."""
    clock = int.from_bytes(d[0:2], 'little')
    if not clock:
        return None
    return {'clock_khz': clock * 10,
            'h': d[2] | (d[4] & 0xF0) << 4, 'hblank': d[3] | (d[4] & 0x0F) << 8,
            'v': d[5] | (d[7] & 0xF0) << 4, 'vblank': d[6] | (d[7] & 0x0F) << 8,
            'interlaced': bool(d[17] & 0x80)}


def timings(edid):
    """Every detailed timing in the base block and the CEA extensions, as (bytes, parsed)."""
    found = []
    if len(edid) < 128:
        return found
    for offset in (54, 72, 90, 108):
        t = parse_dtd(edid[offset:offset + 18])
        if t:
            found.append((bytes(edid[offset:offset + 18]), t))
    for start in range(128, len(edid) - 127, 128):
        block = edid[start:start + 128]
        if block[0] != 0x02 or block[2] < 4:
            continue
        offset = block[2]
        while offset + 18 <= 127:
            t = parse_dtd(block[offset:offset + 18])
            if not t:
                break
            found.append((bytes(block[offset:offset + 18]), t))
            offset += 18
    return found


def native_1920x720(edid):
    """The panel's own 1920 x 720 timing near 60 Hz, if its EDID has one."""
    best = None
    for raw, t in timings(edid):
        if t['h'] != 1920 or t['v'] != 720 or t['interlaced']:
            continue
        refresh = t['clock_khz'] * 1000 / ((t['h'] + t['hblank']) * (t['v'] + t['vblank']))
        if 50 <= refresh <= 75 and (best is None or abs(refresh - 60) < best[0]):
            best = (abs(refresh - 60), raw)
    return best[1] if best else None


def cvt_rb_1920x720():
    """1920 x 720 at 60 Hz, VESA CVT reduced blanking: 2080 x 741 total, 92.25 MHz, H+ V-."""
    h, hfp, hsync, hblank = 1920, 48, 32, 160
    v, vfp, vsync, vblank = 720, 3, 10, 21
    clock = 9225  # x 10 kHz
    width_mm, height_mm = 292, 110  # A typical 12.3 inch 1920 x 720 bar panel
    return bytes([
        clock & 0xFF, clock >> 8,
        h & 0xFF, hblank & 0xFF, (h >> 8) << 4 | hblank >> 8,
        v & 0xFF, vblank & 0xFF, (v >> 8) << 4 | vblank >> 8,
        hfp & 0xFF, hsync & 0xFF, (vfp & 0x0F) << 4 | (vsync & 0x0F),
        (hfp >> 8) << 6 | (hsync >> 8) << 4 | (vfp >> 4) << 2 | vsync >> 4,
        width_mm & 0xFF, height_mm & 0xFF, (width_mm >> 8) << 4 | height_mm >> 8,
        0, 0,
        0x1A,  # Digital separate sync, vsync negative, hsync positive
    ])


def text_descriptor(tag, text):
    body = text.encode('ascii')[:13]
    body = body + (b'\n' + b' ' * 12 if len(body) < 13 else b'')
    return bytes([0, 0, 0, tag, 0]) + body[:13]


def build_edid(dtd):
    """Two blocks: a base block whose only mode is `dtd`, and a CEA block that says HDMI with
    two-channel audio, so sound through the screen keeps working. No other modes anywhere."""
    base = bytearray(128)
    base[0:8] = bytes.fromhex('00ffffffffffff00')
    base[8:10] = OUR_MAKER                            # Manufacturer "FOX" (packed letters)
    base[10:12] = (0x0720).to_bytes(2, 'little')      # Product code
    base[16], base[17] = 41, 2026 - 1990              # Week, year
    base[18], base[19] = 1, 3                         # EDID 1.3
    base[20] = 0x80                                   # Digital input
    base[21], base[22] = (dtd[12] | (dtd[14] & 0xF0) << 4) // 10 or 29, (dtd[13] | (dtd[14] & 0x0F) << 8) // 10 or 11
    base[23] = 120                                    # Gamma 2.2
    base[24] = 0x0A                                   # RGB colour, first timing is the preferred one
    base[25:35] = bytes.fromhex('ee91a3544c99260f5054')   # sRGB chromaticity
    base[35:38] = b'\x00\x00\x00'                     # No established timings
    base[38:54] = b'\x01\x01' * 8                     # No standard timings
    base[54:72] = dtd
    # No range-limits descriptor: from one, Linux adds every standard mode that fits inside it.
    base[72:90] = text_descriptor(0xFC, 'Fox Body dash')
    base[90:108] = bytes([0, 0, 0, 0x10, 0]) + bytes(13)
    base[108:126] = bytes([0, 0, 0, 0x10, 0]) + bytes(13)
    base[126] = 1
    base[127] = -sum(base[:127]) % 256
    cea = bytearray(128)
    blocks = bytes([0x23, 0x09, 0x07, 0x07,            # Audio: LPCM, 2 channels, 32-48 kHz, 16-24 bit
                    0x83, 0x01, 0x00, 0x00,            # Speakers: front left and right
                    0x65, 0x03, 0x0C, 0x00, 0x10, 0x00])  # HDMI vendor block, physical address 1.0.0.0
    cea[0:4] = bytes([0x02, 0x03, 4 + len(blocks), 0x40])  # Basic audio, no video data block
    cea[4:4 + len(blocks)] = blocks
    cea[127] = -sum(cea[:127]) % 256
    return bytes(base) + bytes(cea)


# --------------------------------------------------------------------------- boot files


def boot_dir():
    for folder in (os.environ.get('FROGDASH_BOOT'), '/boot/firmware', '/boot'):
        if folder and (Path(folder) / 'config.txt').is_file() and (Path(folder) / 'cmdline.txt').is_file():
            return Path(folder)
    return None


def with_block(text, name, lines):
    """config.txt with Frogdash's marked block `name` replaced by `lines` (None: removed).
    A block always ends with [all], so whatever follows it applies as before."""
    begin, end = f'# frogdash-{name} begin', f'# frogdash-{name} end'
    out, skipping = [], False
    for line in text.splitlines():
        if line.strip() == begin:
            skipping = True
            continue
        if skipping:
            skipping = line.strip() != end
            continue
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    if lines is not None:
        out += ['', begin, *lines, '[all]', end]
    return '\n'.join(out) + '\n'


def has_block(text, name):
    return any(line.strip() == f'# frogdash-{name} begin' for line in text.splitlines())


def forced_connectors(proc_cmdline):
    """Connectors the firmware forced on (video=HDMI-A-n:...D): the panel may not signal hotplug."""
    return sorted(set(re.findall(r'video=(HDMI-A-\d):\S*D(?:\s|$)', proc_cmdline + ' ')))


def screen_cmdline(cmdline, forced):
    """The kernel command line with the 1920 x 720 EDID, keeping every forced connector forced."""
    words = [w for w in cmdline.split() if not w.startswith(('video=HDMI-', 'drm.edid_firmware='))]
    words.append(f'drm.edid_firmware=edid/{EDID_NAME}')
    words += [f'video={name}:1920x720@60D' for name in forced]
    return ' '.join(words) + '\n'


def plain_cmdline(cmdline):
    return ' '.join(w for w in cmdline.split() if not w.startswith('drm.edid_firmware=edid/frogdash')
                    and not re.fullmatch(r'video=HDMI-A-\d:1920x720@60D?', w)) + '\n'


SCREEN_CONFIG = ['disable_fw_kms_setup=1',
                 'hdmi_edid_file:0=1', f'hdmi_edid_filename:0={EDID_NAME}',
                 'hdmi_edid_file:1=1', f'hdmi_edid_filename:1={EDID_NAME}']
BOOT_CONFIG = ['[all]', 'disable_splash=1', 'boot_delay=0']


def sync():
    getattr(os, 'sync', lambda: None)()   # Not on Windows, where the tests run


def write_atomic(path, text):
    # The boot partition is FAT: a power cut mid-write must leave the old file or the new one.
    tmp = path.with_name(path.name + '.frogdash-tmp')
    with open(tmp, 'w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------- the Pi


def read(path, binary=False):
    try:
        return path.read_bytes() if binary else path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return b'' if binary else ''


def connectors():
    found = []
    for status in sorted(DRM.glob('card*-HDMI-A-*/status')):
        folder = status.parent
        edid = read(folder / 'edid', True)
        modes = list(dict.fromkeys(read(folder / 'modes').split()))
        found.append({'name': folder.name.split('-', 1)[1], 'status': read(status).strip(), 'edid_bytes': len(edid),
                      'edid_ok': edid_ok(edid), 'panel_1920x720': bool(native_1920x720(edid)) if edid_ok(edid) else False,
                      'modes': modes[:30], 'mode_count': len(modes)})
    return found


def panel_edid():
    """The connected panel's own EDID, when it can be read and is valid."""
    for status in sorted(DRM.glob('card*-HDMI-A-*/status')):
        if read(status).strip() == 'connected':
            edid = read(status.parent / 'edid', True)
            if edid_ok(edid) and edid[8:10] != OUR_MAKER:   # Not our own, once it is in use
                return edid
    return None


def in_tryboot():
    flag = read(TRYBOOT_FLAG, True)
    return len(flag) >= 4 and int.from_bytes(flag[:4], 'big') == 1


def boot_id():
    return read((PROC / 'sys/kernel/random/boot_id')).strip()


def run(*args, timeout=8):
    try:
        result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout, env={**os.environ, 'LC_ALL': 'C'})
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''


def status(state, message, **extra):
    old = {}
    try:
        old = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        pass
    body = {**old, **extra, 'state': state, 'message': message, 'time': int(time.time())}
    write_atomic(STATUS, json.dumps(body))
    os.chmod(STATUS, 0o644)
    return body


def survey():
    """What the Pi sees: for the dash and the diagnostics download."""
    boot = boot_dir()
    config = read(boot / 'config.txt') if boot else ''
    relevant = [l.strip() for l in config.splitlines() if re.match(r'\s*(\[|hdmi_|disable_|dtoverlay=vc4|boot_delay|display_|max_framebuffer|config_hdmi|framebuffer_)', l)]
    cmdline = re.sub(r'smsc95xx\.macaddr=\S+', 'smsc95xx.macaddr=(hidden)', read((PROC / 'cmdline')).strip())
    first = [l for l in run('journalctl', '-b', '--no-pager', '-o', 'short-monotonic', '--grep=first render heartbeat', timeout=15).splitlines() if 'Frogdash kiosk' in l]
    return {'connectors': connectors(), 'cmdline': cmdline, 'config': relevant[-40:],
            'applied': has_block(config, 'screen'), 'boot_speedups': has_block(config, 'boot'),
            'edid_installed': (FIRMWARE / 'edid' / EDID_NAME).is_file(), 'tryboot_now': in_tryboot(),
            'boot_time': run('systemd-analyze', 'time').splitlines()[:1], 'first_render': first[:1],
            'bootloader': run('vcgencmd', 'bootloader_version').splitlines()[:1]}


def install():
    """Setup's part: the EDID files and the boot speed-ups. Changes nothing about the screen
    mode itself; that is only ever done through a trial."""
    boot = boot_dir()
    if not boot:
        return 'skipped', 'No Raspberry Pi boot partition found'
    panel = panel_edid()
    current = read(FIRMWARE / 'edid' / EDID_NAME, True)
    if panel is None and edid_ok(current) and current[8:10] == OUR_MAKER:
        edid = current     # Ours is in use, so the panel's own cannot be read: keep what was tried.
    else:
        edid = build_edid(native_1920x720(panel or b'') or cvt_rb_1920x720())
    changed = []
    for target in (FIRMWARE / 'edid' / EDID_NAME, boot / EDID_NAME):
        if read(target, True) != edid:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(edid)
            changed.append(str(target))
    config = read(boot / 'config.txt')
    wanted = with_block(config, 'boot', BOOT_CONFIG)
    if wanted != config:
        write_atomic(boot / 'config.txt', wanted)
        changed.append('config.txt: no rainbow screen, no boot delay')
    applied = has_block(read(boot / 'config.txt'), 'screen')
    note = ('The screen gets exactly 1920 x 720' if applied else
            'Ready: try exact 1920 x 720 under Dash management, Support')
    return ('done' if changed else 'ok'), note


def request_trial():
    boot = boot_dir()
    if not boot:
        return status('failed', 'No Raspberry Pi boot partition found')
    if not re.search(r'Raspberry Pi (4|5|400|500)|Compute Module (4|5)', read((PROC / 'device-tree/model'))):
        return status('failed', 'A trial start needs a Raspberry Pi 4 or 5')
    tryboot_txt = boot / 'tryboot.txt'
    if tryboot_txt.exists() and TRYBOOT_MARK not in read(tryboot_txt):
        return status('failed', 'tryboot.txt on the boot partition belongs to something else, so no trial was started')
    install()
    cmdline = read(boot / 'cmdline.txt')
    if not (boot / 'cmdline.txt.frogdash-before').exists():
        shutil.copy2(boot / 'cmdline.txt', boot / 'cmdline.txt.frogdash-before')
    write_atomic(boot / TRIAL_CMDLINE, screen_cmdline(plain_cmdline(cmdline), forced_connectors(read((PROC / 'cmdline')))))
    # A trial start reads the [tryboot] section of config.txt, or tryboot.txt in its place,
    # depending on the firmware: both get the trial settings, and a normal start reads neither.
    config = read(boot / 'config.txt')
    write_atomic(tryboot_txt, TRYBOOT_MARK + '\n' + with_block(config, 'screen-trial', ['[all]', f'cmdline={TRIAL_CMDLINE}', *SCREEN_CONFIG]))
    write_atomic(boot / 'config.txt', with_block(config, 'screen-trial', ['[tryboot]', f'cmdline={TRIAL_CMDLINE}', *SCREEN_CONFIG]))
    write_atomic(TRIAL, json.dumps({'boot_id': boot_id(), 'started': int(time.time())}))
    status('restarting', 'Restarting to try exact 1920 x 720. If the screen stays dark, wait: it goes back by itself within two minutes')
    sync()
    subprocess.run(['/usr/sbin/reboot', '0 tryboot'], timeout=30)
    return None


def end_trial(boot):
    if boot:
        write_atomic(boot / 'config.txt', with_block(read(boot / 'config.txt'), 'screen-trial', None))
        try:
            (boot / TRIAL_CMDLINE).unlink()
        except OSError:
            pass
        if TRYBOOT_MARK in read(boot / 'tryboot.txt'):
            (boot / 'tryboot.txt').unlink()
    try:
        TRIAL.unlink()
    except OSError:
        pass


def trial_applied():
    return f'drm.edid_firmware=edid/{EDID_NAME}' in read((PROC / 'cmdline'))


def request_keep():
    boot = boot_dir()
    if not TRIAL.exists() or not in_tryboot() or not trial_applied() or not boot:
        return status(read_state(), 'Nothing to keep: no trial is running')
    write_atomic(boot / 'cmdline.txt', read(boot / TRIAL_CMDLINE))
    write_atomic(boot / 'config.txt', with_block(read(boot / 'config.txt'), 'screen', ['[all]', *SCREEN_CONFIG]))
    end_trial(boot)
    return status('kept', 'The screen now gets exactly 1920 x 720 at every start', **survey())


def request_revert():
    boot = boot_dir()
    if not boot:
        return status('failed', 'No Raspberry Pi boot partition found')
    if TRIAL.exists() and in_tryboot():
        # "Go back now" during a trial: a normal start is the old setup.
        end_trial(boot)
        status('reverting', 'Going back to the previous screen setup')
        sync()
        subprocess.run(['/usr/sbin/reboot'], timeout=30)
        return None
    end_trial(boot)
    config = read(boot / 'config.txt')
    if not has_block(config, 'screen'):
        return status('original', "The screen already uses its own modes")
    backup = boot / 'cmdline.txt.frogdash-before'
    write_atomic(boot / 'cmdline.txt', read(backup) if backup.exists() else plain_cmdline(read(boot / 'cmdline.txt')))
    write_atomic(boot / 'config.txt', with_block(config, 'screen', None))
    status('restarting', "Restarting with the screen's own modes")
    sync()
    subprocess.run(['/usr/sbin/reboot'], timeout=30)
    return None


def read_state():
    try:
        return json.loads(STATUS.read_text()).get('state', 'idle')
    except (OSError, ValueError):
        return 'idle'


def after_start(wait=time.sleep, clock=time.monotonic):
    """At every start. A trial the bootloader really started waits a minute for KEEP; a
    trial that did not start (old bootloader, power cut) is cleaned up."""
    boot = boot_dir()
    trial = None
    try:
        trial = json.loads(TRIAL.read_text())
    except (OSError, ValueError):
        pass
    if trial and trial.get('boot_id') != boot_id():
        if not in_tryboot():
            end_trial(boot)
            status('failed', 'The Pi started normally instead of trying 1920 x 720: its bootloader may be too old for a trial start. Nothing was changed')
        elif not trial_applied():
            # The trial start ran without the trial command line: do not judge or keep it.
            end_trial(boot)
            status('failed', 'The trial start did not take the new screen settings. Nothing was changed; restarting normally')
            sync()
            subprocess.run(['/usr/sbin/reboot'], timeout=30)
            return
        else:
            deadline = clock() + KEEP_WINDOW_S
            status('trial', 'Trying exact 1920 x 720. Press KEEP if the dash looks right', deadline_s=KEEP_WINDOW_S, started=int(time.time()))
            while clock() < deadline:
                if not TRIAL.exists():  # KEEP arrived (request_keep ended the trial)
                    break
                wait(.5)
            else:
                end_trial(boot)
                status('reverting', 'No answer: going back to the previous screen setup')
                sync()
                subprocess.run(['/usr/sbin/reboot'], timeout=30)
                return
    elif read_state() in ('restarting', 'trial', 'reverting'):
        applied = bool(boot) and has_block(read(boot / 'config.txt'), 'screen')
        if read_state() == 'reverting':
            status('original', 'Exact 1920 x 720 was not kept, so the screen is back to its own modes')
        else:
            status('applied' if applied else 'original', 'Exact 1920 x 720 is in use' if applied else "The screen uses its own modes")
    # How long the start took is known once it is over.
    wait(45)
    status(read_state(), message(), **survey())


def message():
    try:
        return json.loads(STATUS.read_text()).get('message', '')
    except (OSError, ValueError):
        return ''


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else None
    if action == 'survey':
        status(read_state(), message(), **survey())
    elif action == 'install':
        result, note = install()
        print(f'{result}: {note}')
    elif action == 'boot':
        after_start()
    else:
        word = read(REQUEST).strip()
        try:
            REQUEST.unlink()
        except OSError:
            pass
        {'trial': request_trial, 'keep': request_keep, 'revert': request_revert}.get(word, lambda: None)()


if __name__ == '__main__':
    main()
