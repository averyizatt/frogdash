#!/bin/sh
# Everything this version of the dash needs on the Pi beyond its own files, done as root
# so that nothing ever has to be typed over SSH. Run by the updater after every update
# (tools/frogdash_update.sh, also on "Already up to date"), and when the dash asks at
# start because this file changed (request word 'setup'), or by hand:
#   sudo sh /opt/frogdash/tools/frogdash_setup.sh
#
# Each step looks at the Pi first and acts only when something is missing, so running it
# again changes nothing. A step that needs the internet waits for the next Update now.
# A NEW REQUIREMENT ON THE PI IS ADDED HERE AS A STEP, never as a command for the owner.
# The outcome of every step is written to setup-status.json for System check.
REPO=${FROGDASH_REPO:-/opt/frogdash}
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
UNITS=${FROGDASH_UNITS:-/etc/systemd/system}
ETC=${FROGDASH_ETC:-/etc}
OPT=${FROGDASH_OPT:-/opt}
STATUS=$STATE/setup-status.json
# Services that are not started by a request file but belong to every install.
SERVICES="frogdash-netkeeper"
# TunerStudio MS for Linux, from its publisher. The archive must match this SHA-256.
TS_URL=${FROGDASH_TS_URL:-https://www.tunerstudio.com/downloads2/TunerStudioMS_v3.3.01.tar.gz}
TS_SHA=${FROGDASH_TS_SHA:-4f4781a6ff90127ef36672cc43d3edc78c4f61ef682dca38a02f9e17e652517f}
# The dash compares this with its own copy of the file to see whether setup has run.
STAMP=$(sha256sum "$0" 2>/dev/null | cut -c1-12)
online=${1:-}   # 'online' from the updater, which has just reached GitHub; else found out when needed

steps=""; did=""; restart_screen=""; restart_dash=""; apt_ready=""
write_status() {  # running: true or false
    printf '{"stamp":"%s","running":%s,"time":%s,"steps":[%s]}\n' "$STAMP" "$1" "$(date +%s)" "$steps" > "$STATUS.tmp"
    chmod 644 "$STATUS.tmp"; mv "$STATUS.tmp" "$STATUS"
}
step() {  # name, result (ok, done, waiting, failed, skipped), detail
    detail=$(printf '%s' "$3" | tr -cd 'A-Za-z0-9 .,:;()/_+-' | cut -c1-200)
    steps="$steps${steps:+,}{\"name\":\"$1\",\"result\":\"$2\",\"detail\":\"$detail\"}"
    [ "$2" = done ] && did="$did${did:+, }$1"
    write_status true
}
is_online() {
    if [ -z "$online" ]; then
        if timeout 10 git -C "$REPO" ls-remote --exit-code origin HEAD >/dev/null 2>&1; then online=online; else online=offline; fi
    fi
    [ "$online" = online ]
}
have() { dpkg -s "$1" 2>/dev/null | grep -q '^Status: install ok installed'; }
install_packages() {
    if [ -z "$apt_ready" ]; then
        # An install cut short earlier (power off, a timeout) is finished first, or apt refuses to work.
        timeout 600 dpkg --configure -a >/dev/null 2>&1
        timeout 300 apt-get update -q >/dev/null 2>&1; apt_ready=1
    fi
    DEBIAN_FRONTEND=noninteractive timeout 1500 apt-get install -y -q "$@" >/dev/null 2>&1
}
fetch() {  # url, file
    if command -v curl >/dev/null 2>&1; then curl -fsSL -m 900 -o "$2" "$1" 2>/dev/null
    else python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2" 2>/dev/null
    fi
}
kiosk_user() {  # The user the dash screen runs as: the name after frogdash-console@
    for link in "$UNITS"/*.wants/frogdash-console@*.service; do
        [ -e "$link" ] || [ -L "$link" ] || continue
        name=${link##*@}; echo "${name%.service}"; return
    done
}
NEEDS_NET="needs the internet: press Update now with Wi-Fi connected"

write_status true

# --- Helpers: update, Wi-Fi and GPS recovery (request-file units), and the Wi-Fi keeper ---
added=""; broken=""
install_unit() {  # service name without extension, the unit to enable
    cp "$REPO/hardware/systemd/$1.service" "$UNITS/" || return 1
    [ "$2" = "$1.service" ] || cp "$REPO/hardware/systemd/$1.path" "$UNITS/" || return 1
    systemctl daemon-reload
    systemctl enable --now "$2" >/dev/null 2>&1
}
for path in "$REPO"/hardware/systemd/frogdash-*.path; do
    [ -f "$path" ] || continue
    name=$(basename "$path" .path)
    [ -f "$REPO/hardware/systemd/$name.service" ] || continue
    [ -f "$UNITS/$name.path" ] && [ -f "$UNITS/$name.service" ] && systemctl is-enabled --quiet "$name.path" && continue
    if install_unit "$name" "$name.path"; then added="$added ${name#frogdash-}"; else broken="$broken ${name#frogdash-}"; fi
done
for name in $SERVICES; do
    [ -f "$REPO/hardware/systemd/$name.service" ] || continue
    [ -f "$UNITS/$name.service" ] && systemctl is-enabled --quiet "$name.service" && continue
    if install_unit "$name" "$name.service"; then added="$added ${name#frogdash-}"; else broken="$broken ${name#frogdash-}"; fi
done
if [ -n "$broken" ]; then step "Dash helpers" failed "Could not install:$broken"
elif [ -n "$added" ]; then step "Dash helpers" done "Installed:$added"
else step "Dash helpers" ok "All installed"
fi

# --- GPS service: start with the Pi, read at once, and open only the GPS receiver ---
config=$ETC/default/gpsd
if [ ! -f "$config" ]; then
    step "GPS service" skipped "gpsd is not installed"
elif grep -qx 'USBAUTO="false"' "$config" && grep -q '^DEVICES="..*"' "$config" && grep -q '^GPSD_OPTIONS=".*-n' "$config"; then
    systemctl is-enabled --quiet gpsd.service || systemctl enable gpsd.service >/dev/null 2>&1
    step "GPS service" ok "Starts with the Pi and opens only the GPS receiver"
else
    FROGDASH_STATE=$STATE FROGDASH_GPSD_DEFAULT=$config sh "$REPO/tools/frogdash_gps.sh" repin >/dev/null 2>&1
    said=$(sed -n 's/.*"message":"\([^"]*\)".*/\1/p' "$STATE/gps-status.json" 2>/dev/null)
    if grep -q '"result":"ok"' "$STATE/gps-status.json" 2>/dev/null; then step "GPS service" done "$said"
    else step "GPS service" waiting "${said:-No answer from the GPS helper}. Done by itself once the receiver is plugged in"
    fi
fi

# --- Clock from GPS: chrony reads the time gpsd shares ---
if [ ! -f "$REPO/hardware/chrony/frogdash-gps.conf" ] || ! command -v dpkg >/dev/null 2>&1; then
    step "Clock from GPS" skipped "Not a Debian system"
else
    result=ok; detail="chrony sets the clock from the GPS"
    if ! have chrony; then
        if ! is_online; then result=waiting; detail="chrony $NEEDS_NET"
        elif install_packages chrony && have chrony; then result=done; detail="Installed chrony"
        else result=failed; detail="Could not install chrony"
        fi
    fi
    if [ $result = ok ] || [ $result = done ]; then
        if ! cmp -s "$REPO/hardware/chrony/frogdash-gps.conf" "$ETC/chrony/conf.d/frogdash-gps.conf"; then
            mkdir -p "$ETC/chrony/conf.d" && cp "$REPO/hardware/chrony/frogdash-gps.conf" "$ETC/chrony/conf.d/" &&
                systemctl restart chrony >/dev/null 2>&1 && result=done && detail="chrony now sets the clock from the GPS"
        fi
    fi
    step "Clock from GPS" $result "$detail"
fi

# --- TunerStudio on the dash screen: Java and an X display, the program, the serial port ---
user=$(kiosk_user)
home=$(getent passwd "$user" 2>/dev/null | cut -d: -f6)
if ! command -v dpkg >/dev/null 2>&1; then
    step "TunerStudio: Java and display" skipped "Not a Debian system"
else
    need=""
    for package in xwayland default-jre; do have $package || need="$need $package"; done
    if [ -z "$need" ]; then step "TunerStudio: Java and display" ok "Installed"
    elif ! is_online; then step "TunerStudio: Java and display" waiting "Missing$need: $NEEDS_NET"
    elif install_packages $need; then restart_screen=1; step "TunerStudio: Java and display" done "Installed$need"
    else step "TunerStudio: Java and display" failed "Could not install$need"
    fi
fi
found=""
for folder in "$home/TunerStudioMS" "$OPT/TunerStudioMS" /usr/local/TunerStudioMS; do
    [ -f "$folder/TunerStudio.sh" ] && found=$folder
done
if [ -n "$found" ]; then
    step "TunerStudio: program" ok "In $found"
elif ! is_online; then
    step "TunerStudio: program" waiting "Not downloaded yet: $NEEDS_NET"
else
    # Into the screen user's home when there is one, so TunerStudio can keep its own files there.
    if [ -n "$home" ] && [ -d "$home" ]; then target=$home; else target=$OPT; fi
    work=$(mktemp -d)
    if ! fetch "$TS_URL" "$work/ts.tar.gz"; then
        step "TunerStudio: program" failed "Download failed from tunerstudio.com"
    elif [ "$(sha256sum "$work/ts.tar.gz" | cut -c1-64)" != "$TS_SHA" ]; then
        step "TunerStudio: program" failed "The download is not the expected file, so it was not installed"
    elif tar -xzf "$work/ts.tar.gz" -C "$target" --no-same-owner && [ -f "$target/TunerStudioMS/TunerStudio.sh" ]; then
        chmod -R a+rX "$target/TunerStudioMS"
        [ "$target" = "$home" ] && chown -R "$user": "$target/TunerStudioMS"
        step "TunerStudio: program" done "Installed in $target/TunerStudioMS"
    else
        step "TunerStudio: program" failed "Could not unpack into $target"
    fi
    rm -rf "$work"
fi
if [ -z "$user" ]; then
    step "TunerStudio: serial port" skipped "The dash screen service is not installed"
elif id -nG "$user" 2>/dev/null | tr ' ' '\n' | grep -qx dialout; then
    step "TunerStudio: serial port" ok "$user can open the tuning cable"
elif usermod -aG dialout "$user" >/dev/null 2>&1; then
    restart_screen=1; step "TunerStudio: serial port" done "$user can now open the tuning cable"
else
    step "TunerStudio: serial port" failed "Could not add $user to the dialout group"
fi

# --- Phone hotspot: the dash's own Wi-Fi network for logs, faults and updates from a phone ---
# Off until switched on under Controls > Wi-Fi. Made on a Wi-Fi adapter the dash cam does
# not use, with a password generated on the Pi and shown only on the dash.
hotspot=$ETC/frogdash/hotspot.json
if ! command -v nmcli >/dev/null 2>&1; then
    step "Phone hotspot" skipped "NetworkManager is not installed"
else
    made=""; problem=""
    if [ ! -f "$hotspot" ]; then
        camera=$(nmcli -g connection.interface-name con show dashcam 2>/dev/null)
        chosen=""
        for device in $(nmcli -t -f DEVICE,TYPE dev 2>/dev/null | awk -F: '$2=="wifi"{print $1}'); do
            [ "$device" = "$camera" ] && continue
            if [ "$(LC_ALL=C nmcli -g WIFI-PROPERTIES.AP device show "$device" 2>/dev/null)" = yes ]; then chosen=$device; break; fi
        done
        if [ -z "$chosen" ]; then problem="waiting"
        elif python3 "$REPO/tools/setup_hotspot.py" --interface "$chosen" --ssid "Foxbody Dash" >/dev/null 2>&1 && [ -f "$hotspot" ]; then made=1
        else problem="failed"
        fi
    fi
    if [ "$problem" = waiting ]; then
        step "Phone hotspot" waiting "No free Wi-Fi adapter that can be a hotspot (the dash cam uses ${camera:-none})"
    elif [ "$problem" = failed ]; then
        step "Phone hotspot" failed "Could not create the hotspot on $chosen"
    else
        if ! { [ -f "$UNITS/frogdash-hotspot.service" ] && systemctl is-enabled --quiet frogdash-hotspot.service; }; then
            install_unit frogdash-hotspot frogdash-hotspot.service && made=1
        fi
        # Lets the dash service talk to the hotspot helper; it takes effect when the dash restarts.
        if ! cmp -s "$REPO/config/hotspot-service.conf" "$UNITS/frogdash.service.d/hotspot.conf"; then
            mkdir -p "$UNITS/frogdash.service.d" && cp "$REPO/config/hotspot-service.conf" "$UNITS/frogdash.service.d/hotspot.conf" &&
                systemctl daemon-reload && made=1 && restart_dash=1
        fi
        if [ -n "$made" ]; then step "Phone hotspot" done "Ready: switch it on under Controls, Wi-Fi"
        else step "Phone hotspot" ok "Ready: switch it on under Controls, Wi-Fi"
        fi
    fi
fi

# A new display package or group reaches the screen only when its session starts again.
[ -n "$restart_screen" ] && [ -n "$user" ] && systemctl try-restart "frogdash-console@$user.service" >/dev/null 2>&1

write_status false
# The dash picks up its new permission on a restart. Last, so the status above is what it reads.
[ -n "$restart_dash" ] && systemctl restart frogdash.service >/dev/null 2>&1
[ -n "$did" ] && echo "Set up: $did"
exit 0
