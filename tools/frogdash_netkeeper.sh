#!/bin/sh
# Wi-Fi keeper: keeps the dash cam's Wi-Fi connection up without anyone typing commands.
# Every 10 s, if the dash cam connection is down and nothing is borrowing the adapter
# (an update or the Wi-Fi menu holds /run/frogdash-wifi.lock), rescan and reconnect.
# A stale lock (older than 5 minutes) is ignored so a crashed helper cannot block it.
# The phone hotspot holds its own lock while it is on the dash cam's adapter: it has
# priority, and the cameras come back when it is switched off.
LOCKS="${FROGDASH_WIFI_LOCKS:-/run/frogdash-wifi.lock /run/frogdash-connect/hotspot.lock}"
borrowed() {
    for lock in $LOCKS; do
        [ -e "$lock" ] || continue
        age=$(( $(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || echo 0) ))
        [ "$age" -lt 300 ] && return 0
        rm -f "$lock"
    done
    return 1
}
while true; do
    sleep ${FROGDASH_KEEPER_PERIOD:-10}
    nmcli -t -f NAME con show 2>/dev/null | grep -qx dashcam || continue   # No dash cam profile.
    borrowed && continue
    nmcli -t -f NAME con show --active | grep -qx dashcam && continue      # Already connected.
    device=$(nmcli -g connection.interface-name con show dashcam 2>/dev/null)
    [ -n "$device" ] || continue
    # Leave a network the adapter was left on (after an update or a manual test).
    other=$(nmcli -t -f NAME,DEVICE con show --active | awk -F: -v d="$device" '$2==d{print $1}')
    [ -n "$other" ] && nmcli con down "$other" >/dev/null 2>&1
    nmcli dev wifi rescan ifname "$device" >/dev/null 2>&1
    sleep 5
    if nmcli -t -f SSID dev wifi list ifname "$device" 2>/dev/null | grep -q "^DC-"; then
        nmcli --wait 20 con up dashcam >/dev/null 2>&1 && echo "Reconnected to the dash cam"
    fi
done
