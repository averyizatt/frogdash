#!/bin/sh
# Frogdash on a freshly flashed SD card: everything from a blank Raspberry Pi OS Lite (64-bit)
# to the dash on the screen, in one run. Run it once, as root, from the user who will own
# the screen (the one made in Raspberry Pi Imager), with internet:
#
#   curl -fsSL https://raw.githubusercontent.com/averyizatt/frogdash/main/tools/frogdash_install.sh | sudo sh
#
# Then restart the Pi. Afterwards, check that every part runs:
#
#   sudo sh /opt/frogdash/tools/frogdash_install.sh --check
#
# Options: --user NAME (the screen's user; default: the one running sudo)
#          --oscillator HZ (the MCP2515 board's crystal; default 8000000, the car's Waveshare
#                           RS485 CAN HAT; 12000000 for the HAT batches with a 12 MHz crystal)
#          --interrupt GPIO (default 25)
#          --no-pisugar (skip installing the PiSugar 3 software)
# Running it again is safe: each step looks first and changes only what is missing. From
# then on, Update now on the dash keeps everything up to date (tools/frogdash_setup.sh).
REPO=/opt/frogdash
URL=https://github.com/averyizatt/frogdash.git
LOG=/var/log/frogdash-install.log
user=${SUDO_USER:-}; oscillator=8000000; interrupt=25; check=""; pisugar=1
while [ $# -gt 0 ]; do
    case "$1" in
        --user) user=$2; shift;;
        --oscillator) oscillator=$2; shift;;
        --interrupt) interrupt=$2; shift;;
        --check) check=1;;
        --no-pisugar) pisugar="";;
        *) echo "Unknown option: $1"; exit 2;;
    esac
    shift
done

ok() { printf '  \033[32mOK\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; failed=$((failed + 1)); }
warn() { printf '  \033[33mNOTE\033[0m  %s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }
failed=0

[ "$(id -u)" = 0 ] || { echo "Run as root: sudo sh $0"; exit 1; }
if [ -z "$user" ] || [ "$user" = root ] || ! id "$user" >/dev/null 2>&1; then
    echo "Which user owns the screen? Run with sudo from that user, or add --user NAME (not root)."; exit 1
fi
home=$(getent passwd "$user" | cut -d: -f6)
BOOT=/boot/firmware; [ -f $BOOT/config.txt ] || BOOT=/boot

verify() {
    head_ "Checking the install"
    for unit in frogdash.service frogdash-can.service frogdash-update.path "frogdash-console@$user.service" frogdash-guard.service frogdash-rescue.service; do
        if systemctl is-active --quiet "$unit"; then ok "$unit is running"
        elif systemctl is-enabled --quiet "$unit" 2>/dev/null; then bad "$unit is enabled but not running: journalctl -u $unit -b"
        else bad "$unit is not installed"
        fi
    done
    if curl -fsS -m 3 http://127.0.0.1:8080/health >/dev/null 2>&1; then ok "The dash answers on http://127.0.0.1:8080"
    else bad "The dash does not answer: journalctl -u frogdash -b"
    fi
    if ip link show can0 >/dev/null 2>&1; then
        state=$(ip -details link show can0 | sed -n 's/.*can state \([A-Z-]*\).*/\1/p')
        ok "can0 exists (state ${state:-unknown}; ERROR-ACTIVE is normal, BUS-OFF with the car on is not)"
    else bad "No can0: check the MCP2515 wiring and the overlay in $BOOT/config.txt, then restart"
    fi
    if systemctl is-active --quiet gpsd || systemctl is-active --quiet gpsd.socket; then ok "gpsd is running"
    else warn "gpsd is not running (normal until the GPS receiver is plugged in)"
    fi
    for c in /sys/class/drm/card*-HDMI-A-*; do
        [ -e "$c/status" ] || continue
        [ "$(cat "$c/status")" = connected ] && ok "Screen connected on $(basename "$c" | sed 's/card[0-9]-//')"
    done
    throttled=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
    case "$throttled" in
        0x0) ok "Power is good (no under-voltage)";;
        "") warn "Could not read the power flags";;
        *) bad "Under-voltage or throttling ($throttled): check the supply and the cable";;
    esac
    if [ -f /var/lib/frogdash/setup-status.json ]; then
        fails=$(python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print("; ".join(x["name"] + ": " + x["detail"] for x in s.get("steps",[]) if x.get("result")=="failed"))' /var/lib/frogdash/setup-status.json 2>/dev/null)
        if [ -z "$fails" ]; then ok "Pi setup: every step done"; else bad "Pi setup: $fails"; fi
    else warn "Pi setup has not written its status yet"
    fi
    if command -v pisugar-server >/dev/null 2>&1 || systemctl cat pisugar-server >/dev/null 2>&1; then
        systemctl is-active --quiet frogdash-power.service && ok "PiSugar power monitor is running" || bad "PiSugar is installed but frogdash-power is not running"
        [ -x /usr/lib/systemd/system-shutdown/frogdash-pisugar-poweroff ] && ok "PiSugar output turns off after shutdown" || bad "No PiSugar shutdown hook: run the install again"
    else warn "No PiSugar software: run this script again without --no-pisugar (the dash runs without it, but turning the key off cuts power)"
    fi
    echo
    if [ $failed = 0 ]; then echo "Everything checked is working."; else echo "$failed check(s) failed: see above."; fi
}
[ -n "$check" ] && { verify; exit $failed; }

exec 3>&1
step() { head_ "$*"; echo "=== $*" >> $LOG; }
run() { "$@" >> $LOG 2>&1; }
echo "Frogdash install for user $user. Details go to $LOG."

step "1/9 Internet and system"
. /etc/os-release 2>/dev/null
[ "$(uname -m)" = aarch64 ] && ok "64-bit Raspberry Pi OS ($PRETTY_NAME)" || warn "Not 64-bit ($(uname -m)): use Raspberry Pi OS Lite (64-bit)"
[ "${VERSION_CODENAME:-}" = bookworm ] || warn "This Pi runs ${VERSION_CODENAME:-an unknown release}; the car has run on Bookworm. Carrying on."
if curl -fsS -m 15 -o /dev/null https://github.com; then ok "GitHub answers"; else bad "No internet: connect Wi-Fi (sudo nmtui) and run this again"; exit 1; fi

step "2/9 System packages (a few minutes)"
export DEBIAN_FRONTEND=noninteractive
run apt-get update -o DPkg::Lock::Timeout=600
browser=chromium; apt-cache show chromium >/dev/null 2>&1 || browser=chromium-browser
if run apt-get install -y -o DPkg::Lock::Timeout=600 git curl python3-venv python3-pip python3-gps gpsd gpsd-clients can-utils \
        cage "$browser" dbus-user-session libpam-systemd kbd i2c-tools; then ok "Installed git, Python, gpsd, can-utils, Cage and $browser"
else bad "Package install failed: see $LOG"; exit 1
fi

step "3/9 SPI, I2C and the CAN board"
if command -v raspi-config >/dev/null 2>&1; then
    run raspi-config nonint do_spi 0; run raspi-config nonint do_i2c 0; ok "SPI and I2C on"
fi
overlay="dtoverlay=mcp2515-can0,oscillator=$oscillator,interrupt=$interrupt,spimaxfrequency=1000000"
if grep -qx "$overlay" $BOOT/config.txt; then
    ok "MCP2515 overlay already set ($oscillator Hz crystal, interrupt GPIO $interrupt)"
elif grep -q '^#*dtoverlay=mcp2515' $BOOT/config.txt; then
    # An earlier board's line, or one commented out while testing: this one replaces it.
    cp $BOOT/config.txt $BOOT/config.txt.before-frogdash-can
    sed -i "s|^#*dtoverlay=mcp2515.*|$overlay|" $BOOT/config.txt
    sed -i 's|^# Frogdash MCP2515 (.*|# Frogdash MCP2515 ('"$oscillator"' Hz crystal, interrupt GPIO '"$interrupt"')|' $BOOT/config.txt
    grep -q '^dtparam=spi=on' $BOOT/config.txt || sed -i "s|^$overlay|dtparam=spi=on
$overlay|" $BOOT/config.txt
    ok "MCP2515 overlay changed to a $oscillator Hz crystal, interrupt GPIO $interrupt (restart to use it); the old file is config.txt.before-frogdash-can"
else
    cp $BOOT/config.txt $BOOT/config.txt.before-frogdash
    printf '\n[all]\n# Frogdash MCP2515 (%s Hz crystal, interrupt GPIO %s)\ndtparam=spi=on\n%s\n' "$oscillator" "$interrupt" "$overlay" >> $BOOT/config.txt
    ok "MCP2515 overlay added ($oscillator Hz crystal, interrupt GPIO $interrupt); the old file is config.txt.before-frogdash"
fi

step "4/9 The dash's code in $REPO"
if [ -d $REPO/.git ]; then
    run git -C $REPO pull --ff-only && ok "Updated $(git -C $REPO log -1 --format='%h %s')" || warn "Could not update $REPO; using it as it is"
else
    run git clone --depth 50 $URL $REPO && ok "Downloaded $(git -C $REPO log -1 --format='%h %s')" || { bad "Could not download the dash"; exit 1; }
fi

step "5/9 Python environment"
[ -x $REPO/.venv/bin/python ] || run python3 -m venv --system-site-packages $REPO/.venv
if run $REPO/.venv/bin/pip install --disable-pip-version-check -r $REPO/requirements.lock; then ok "Packages installed in $REPO/.venv"
else bad "pip install failed: see $LOG"; exit 1
fi

step "6/9 Services"
[ -f /etc/default/frogdash ] || install -m 0644 $REPO/config/frogdash.env /etc/default/frogdash
for unit in frogdash.service frogdash-can.service frogdash-update.path frogdash-update.service frogdash-console@.service; do
    install -m 0644 $REPO/hardware/systemd/$unit /etc/systemd/system/
done
install -m 0644 $REPO/hardware/pam/frogdash-kiosk /etc/pam.d/frogdash-kiosk
systemctl daemon-reload
run systemctl set-default multi-user.target
run systemctl enable frogdash.service frogdash-can.service frogdash-update.path "frogdash-console@$user.service"
run systemctl start frogdash-update.path
ok "Dash, CAN, updater and the screen for $user enabled; CAN and the screen start at the next restart"

step "7/9 The dash"
run systemctl restart frogdash.service
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do curl -fsS -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS -m 2 http://127.0.0.1:8080/health >/dev/null 2>&1 && ok "The dash is running" || bad "The dash did not start: journalctl -u frogdash -b"

step "8/9 Pi setup: helpers, GPS, clock, hotspot, screen, recovery (several minutes)"
FROGDASH_REPO=$REPO sh $REPO/tools/frogdash_setup.sh online >> $LOG 2>&1
python3 - /var/lib/frogdash/setup-status.json <<'EOF' >&3 2>/dev/null || warn "Could not read the setup's status"
import json, sys
for s in json.load(open(sys.argv[1])).get('steps', []):
    colour = {'ok': 32, 'done': 32, 'skipped': 33, 'waiting': 33}.get(s['result'], 31)
    print(f"  \033[{colour}m{s['result'].upper():5}\033[0m {s['name']}: {s['detail']}")
EOF

step "9/9 PiSugar power"
if [ -n "$pisugar" ] && ! systemctl cat pisugar-server >/dev/null 2>&1; then
    # The vendor's installer, unattended, for the PiSugar 3 Plus (vendor model name "PiSugar 3").
    if curl -fsSL -m 60 -o /tmp/pisugar-power-manager.sh https://cdn.pisugar.com/release/pisugar-power-manager.sh &&
            run bash /tmp/pisugar-power-manager.sh --non-interactive --model "PiSugar 3"; then
        ok "PiSugar software installed"
    else
        bad "PiSugar software did not install: see $LOG, then run this again"
    fi
    rm -f /tmp/pisugar-power-manager.sh
fi
if systemctl cat pisugar-server >/dev/null 2>&1; then
    run systemctl disable pisugar-poweroff.service; run systemctl mask pisugar-poweroff.service
    install -d -m 0755 /usr/local/lib/frogdash-power
    install -m 0644 $REPO/hardware/power/monitor.py /usr/local/lib/frogdash-power/monitor.py
    # The folder does not exist on a fresh Trixie: -D makes it.
    install -D -m 0755 $REPO/hardware/power/frogdash-pisugar-poweroff /usr/lib/systemd/system-shutdown/frogdash-pisugar-poweroff ||
        bad "Could not install the shutdown hook that turns the PiSugar off"
    install -m 0644 $REPO/hardware/systemd/frogdash-power.service /etc/systemd/system/
    [ -f /etc/default/frogdash-power ] || install -m 0644 $REPO/config/frogdash-power.env /etc/default/frogdash-power
    [ -f /etc/default/pisugar-server.before-frogdash ] || cp -a /etc/default/pisugar-server /etc/default/pisugar-server.before-frogdash 2>/dev/null
    install -m 0644 $REPO/config/pisugar-server.default /etc/default/pisugar-server
    run systemctl restart pisugar-server
    run python3 /usr/local/lib/frogdash-power/monitor.py --configure-vendor
    systemctl daemon-reload; run systemctl enable --now frogdash-power.service
    [ -x /usr/lib/systemd/system-shutdown/frogdash-pisugar-poweroff ] && ok "PiSugar: the dash's shutdown on ignition loss is installed"
else
    warn "PiSugar skipped (--no-pisugar): the dash runs, but turning the key off cuts power"
fi

verify
echo
echo "Now restart the Pi: sudo reboot"
echo "The screen shows the dash about 10 seconds after power. Then: sudo sh $REPO/tools/frogdash_install.sh --check"
