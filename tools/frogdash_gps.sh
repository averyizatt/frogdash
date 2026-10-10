#!/bin/sh
# GPS recovery steps for the dash. Run as root by frogdash-gps.service, which starts
# when the dash leaves a request in /var/lib/frogdash/gps-request, or by hand:
#   sudo sh /opt/frogdash/tools/frogdash_gps.sh restart   restart the GPS service
#   sudo sh /opt/frogdash/tools/frogdash_gps.sh repin     point the GPS service at the receiver
#   sudo sh /opt/frogdash/tools/frogdash_gps.sh usb       reset the receiver's USB connection
# Only these three fixed actions exist. The request carries nothing but one of those
# words; anything else is refused. The result is written for the dash to show.
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
SERIAL=${FROGDASH_SERIAL_DIR:-/dev/serial/by-id}
CONFIG=${FROGDASH_GPSD_DEFAULT:-/etc/default/gpsd}
SYS=${FROGDASH_SYS:-/sys}
STATUS=$STATE/gps-status.json
action=${1:-$(tr -cd 'a-z' < "$STATE/gps-request" 2>/dev/null | cut -c1-12)}
rm -f "$STATE/gps-request"

report() {  # result, message
    text=$(printf '%s' "$2" | tr -cd 'A-Za-z0-9 .,:;()/_+-' | cut -c1-240)
    printf '{"action":"%s","result":"%s","message":"%s","time":%s}\n' "$action" "$1" "$text" "$(date +%s)" > "$STATUS.tmp"
    chmod 644 "$STATUS.tmp"; mv "$STATUS.tmp" "$STATUS"
}
restart_service() {
    systemctl enable gpsd.service >/dev/null 2>&1   # Start with the Pi, not on first use.
    systemctl restart gpsd.socket gpsd.service >/dev/null 2>&1
}
# Serial devices that are plainly a GPS receiver, one stable path per line. A generic
# USB serial adapter (such as the ECU tuning cable) is never guessed to be one.
receivers() {
    for path in "$SERIAL"/*; do
        [ -e "$path" ] || continue
        case "$(basename "$path" | tr 'A-Z' 'a-z')" in
            *u-blox*|*ublox*|*gps*|*gnss*|*globalsat*) echo "$path";;
        esac
    done
}
plugged() {
    names=$(ls "$SERIAL" 2>/dev/null | tr '\n' ' ')
    [ -n "$names" ] && echo "serial devices plugged in: $names" || echo "no USB serial device is plugged in"
}

case "$action" in
restart)
    restart_service
    report ok "GPS service restarted"
    ;;
repin)
    found=$(receivers)
    count=$(printf '%s\n' "$found" | grep -c .)
    if [ "$count" = 1 ]; then
        name=$(basename "$found")
        if grep -qxF "DEVICES=\"$found\"" "$CONFIG" 2>/dev/null && grep -qxF 'USBAUTO="false"' "$CONFIG" 2>/dev/null; then
            restart_service
            report ok "GPS service already points at $name; restarted it"
        else
            [ -f "$CONFIG" ] && [ ! -f "$CONFIG.frogdash-bak" ] && cp "$CONFIG" "$CONFIG.frogdash-bak"
            {
                grep -v -e '^DEVICES=' -e '^USBAUTO=' -e '^GPSD_OPTIONS=' "$CONFIG" 2>/dev/null
                echo "DEVICES=\"$found\""
                echo 'GPSD_OPTIONS="-n"'
                echo 'USBAUTO="false"'
            } > "$CONFIG.tmp" && mv "$CONFIG.tmp" "$CONFIG"
            restart_service
            report ok "Pointed the GPS service at $name"
        fi
    elif [ "$count" = 0 ]; then
        report failed "No GPS receiver recognised on USB ($(plugged))"
    else
        report failed "More than one GPS receiver found; set DEVICES in $CONFIG by hand"
    fi
    ;;
usb)
    found=$(receivers | head -n 1)
    if [ -z "$found" ]; then
        report failed "No GPS receiver recognised on USB to reset ($(plugged))"
        exit 1
    fi
    node=$(readlink -f "$SYS/class/tty/$(basename "$(readlink -f "$found")")/device" 2>/dev/null)
    # Walk up from the serial interface to the USB device itself.
    while [ -n "$node" ] && [ "$node" != / ] && [ ! -f "$node/idVendor" ]; do node=$(dirname "$node"); done
    if [ -f "$node/authorized" ]; then
        echo 0 > "$node/authorized"; sleep 1; echo 1 > "$node/authorized"; sleep 2
        restart_service
        report ok "Reset the USB connection of $(basename "$found")"
    else
        report failed "Could not find the USB port of $(basename "$found")"
    fi
    ;;
*)
    action=unknown
    report failed "Unknown GPS action"
    exit 1
    ;;
esac
exit 0
