#!/bin/sh
# Wi-Fi keeper: keeps the dash cam's Wi-Fi connection up while the engine runs, without
# anyone typing commands, and leaves the adapter free while it does not.
#
# Engine running (the dash's /health says so): every 10 s, if the dash cam connection is
# down and nothing is borrowing the adapter (an update or the Wi-Fi menu holds
# /run/frogdash-wifi.lock), rescan and reconnect. A stale lock (older than 5 minutes) is
# ignored so a crashed helper cannot block it. The phone hotspot holds its own lock while
# it is on the dash cam's adapter: it has priority, and the cameras come back when it is
# switched off.
#
# Engine off for a minute, or the dash not answering: the dash cam connection is let go
# and not taken back, so a saved home Wi-Fi or phone hotspot can connect by itself, for
# an update, the phone page or SSH. The dash cam profile does not connect on its own
# (the setup turns its autoconnect off); this keeper brings it up when the engine starts.
LOCKS="${FROGDASH_WIFI_LOCKS:-/run/frogdash-wifi.lock /run/frogdash-connect/hotspot.lock}"
PORT=$(sed -n 's/.*--port[ =]\([0-9][0-9]*\).*/\1/p' /etc/default/frogdash 2>/dev/null | tail -n 1)
HEALTH=${FROGDASH_HEALTH_URL:-http://127.0.0.1:${PORT:-8080}/health}
OFF_AFTER=${FROGDASH_ENGINE_OFF_S:-60}
borrowed() {
    for lock in $LOCKS; do
        [ -e "$lock" ] || continue
        age=$(( $(date +%s) - $(stat -c %Y "$lock" 2>/dev/null || echo 0) ))
        [ "$age" -lt 300 ] && return 0
        rm -f "$lock"
    done
    return 1
}
engine_running() {
    if command -v curl >/dev/null 2>&1; then body=$(curl -fsS -m 3 "$HEALTH" 2>/dev/null)
    else body=$(python3 -c 'import sys, urllib.request; sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=3).read().decode())' "$HEALTH" 2>/dev/null)
    fi
    printf '%s' "$body" | grep -q '"engine_running": *true'
}
last_running=0
released=""
while true; do
    sleep ${FROGDASH_KEEPER_PERIOD:-10}
    nmcli -t -f NAME con show 2>/dev/null | grep -qx dashcam || continue   # No dash cam profile.
    now=$(date +%s)
    engine_running && last_running=$now
    if [ $((now - last_running)) -ge "$OFF_AFTER" ]; then
        # Engine off: give the adapter back to whatever the owner wants to join.
        if [ -z "$released" ] && nmcli -t -f NAME con show --active | grep -qx dashcam; then
            nmcli con down dashcam >/dev/null 2>&1 && echo "Engine off: dash cam Wi-Fi let go, the adapter is free for other networks"
        fi
        released=1
        continue
    fi
    released=""
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
        nmcli --wait 20 con up dashcam >/dev/null 2>&1 && echo "Engine running: reconnected to the dash cam"
    fi
done
