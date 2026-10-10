#!/bin/sh
# Update the dash from GitHub and restart it. Run as root by frogdash-update.service,
# which starts when the dash writes /var/lib/frogdash/update-request (the Update button),
# or by hand:
#   sudo sh /opt/frogdash/tools/frogdash_update.sh            update to the newest version
#   sudo sh /opt/frogdash/tools/frogdash_update.sh rollback   return to the version before the last update
# Only fast-forwards the installed branch; local changes or a failed pull leave the
# running version untouched. The result is written for the dash to show.
#
# A new version has to prove itself after the restart: the service must come up, answer
# on HTTP and stay up, and the screen must reconnect if it was connected before. If it
# does not, the previous version is put back and restarted, and that commit is not
# installed again (a newer one is). The failed start is kept in update-failure.log.
#
# The dash's other root helpers (Wi-Fi, GPS recovery: a .path unit and its .service in
# hardware/systemd) are installed and enabled from here when they are missing, so a new
# one never needs a laptop. The dash asks for that alone with the request word 'helpers'.
REPO=${FROGDASH_REPO:-/opt/frogdash}
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
UNITS=${FROGDASH_UNITS:-/etc/systemd/system}
STATUS=$STATE/update-status.json
PORT=$(sed -n 's/.*--port[ =]\([0-9][0-9]*\).*/\1/p' /etc/default/frogdash 2>/dev/null | tail -n 1)
URL=${FROGDASH_HEALTH_URL:-http://127.0.0.1:${PORT:-8080}/health}
action=${1:-$(cat "$STATE/update-request" 2>/dev/null)}
rm -f "$STATE/update-request"

short() { git -C $REPO rev-parse --short "$1" 2>/dev/null; }
report() {  # state, message
    printf '{"state":"%s","message":"%s","version":"%s","previous":"%s","time":%s}\n' "$1" "$2" \
        "$(short HEAD)" "$(short "$(cat "$STATE/update-previous" 2>/dev/null)")" "$(date +%s)" > "$STATUS.tmp"
    chmod 644 "$STATUS.tmp"; mv "$STATUS.tmp" "$STATUS"
}
probe() {  # The dash's own health page; fails unless the service answers.
    if command -v curl >/dev/null 2>&1; then curl -fsS -m 3 "$URL" 2>/dev/null
    else python3 -c 'import sys, urllib.request; sys.stdout.write(urllib.request.urlopen(sys.argv[1], timeout=3).read().decode())' "$URL" 2>/dev/null
    fi
}
screens() { printf '%s' "$1" | sed -n 's/.*"ui_clients": *\([0-9][0-9]*\).*/\1/p'; }
restarts() { systemctl show -p NRestarts --value frogdash.service 2>/dev/null; }
sync_units() {  # Refresh only the unit files that are already installed.
    changed=0
    for unit in $REPO/hardware/systemd/*.service $REPO/hardware/systemd/*.path; do
        [ -f "$unit" ] || continue
        target=$UNITS/$(basename "$unit")
        if [ -f "$target" ] && ! cmp -s "$unit" "$target"; then cp "$unit" "$target"; changed=1; fi
    done
    [ $changed = 1 ] && systemctl daemon-reload
    return 0
}
install_helpers() {  # Add the dash's path-started helpers that are not installed and enabled yet.
    added=""
    for path in $REPO/hardware/systemd/frogdash-*.path; do
        [ -f "$path" ] || continue
        name=$(basename "$path" .path)
        [ -f "$REPO/hardware/systemd/$name.service" ] || continue
        [ -f "$UNITS/$name.path" ] && [ -f "$UNITS/$name.service" ] && systemctl is-enabled --quiet "$name.path" && continue
        cp "$REPO/hardware/systemd/$name.service" "$REPO/hardware/systemd/$name.path" "$UNITS/" || continue
        systemctl daemon-reload
        systemctl enable --now "$name.path" >/dev/null 2>&1 && added="$added ${name#frogdash-}"
    done
    [ -z "$added" ] || added=". Added helpers:$added"
    return 0
}
restart_dash() {
    systemctl restart frogdash.service
    systemctl try-restart 'frogdash-console@*.service' 2>/dev/null
    return 0
}
healthy() {  # $1 = 1 when a screen was connected before, so it has to come back too
    good=0; tries=0; count=$(restarts)
    while [ $tries -lt 30 ]; do  # About 90 s, at most 3 minutes if every probe hangs.
        tries=$((tries + 1)); sleep 3
        now=$(restarts)
        if [ "$now" = "$count" ] && systemctl is-active --quiet frogdash.service && body=$(probe); then
            good=$((good + 1))
        else
            good=0; count=$now; continue
        fi
        [ $good -ge 5 ] || continue  # Answering for 15 s without a restart: not a crash loop.
        [ "$1" = 1 ] || return 0
        [ "$(screens "$body")" -gt 0 ] 2>/dev/null && return 0
    done
    if [ $good -ge 5 ]; then why="the screen did not reconnect"; else why="the dash service did not stay up"; fi
    return 1
}

if [ "$action" = helpers ]; then  # From the dash at start-up when one is missing. Nothing else changes.
    install_helpers
    exit 0
fi

before=$(git -C $REPO rev-parse HEAD) || { report failed "Not a git checkout: $REPO"; exit 1; }
had_screen=0
[ "$(screens "$(probe)")" -gt 0 ] 2>/dev/null && had_screen=1

if [ "$action" = rollback ]; then
    previous=$(cat "$STATE/update-previous" 2>/dev/null)
    if [ -z "$previous" ] || ! git -C $REPO cat-file -e "$previous^{commit}" 2>/dev/null; then
        report failed "No earlier version is saved to go back to"; exit 1
    fi
    report running "Going back to version $(short "$previous")"
    if ! git -C $REPO reset --keep --quiet "$previous" 2>/dev/null; then
        report failed "Could not go back (local changes on the Pi?)"; exit 1
    fi
    sync_units; restart_dash
    if healthy $had_screen; then
        rm -f "$STATE/update-previous"
        report rolledback "Went back to the previous version. Update now returns to the newest"; exit 0
    fi
    # The older version is the one that does not start: return to where the dash was.
    git -C $REPO reset --keep --quiet "$before"; sync_units; restart_dash
    report failed "The previous version did not start ($why), so the dash stayed on this one"; exit 1
fi

report running "Checking for updates"
# With one usable Wi-Fi adapter, it is normally on the dash cam. If there is no internet,
# borrow that adapter: join a saved Wi-Fi network, update, then return to the dash cam.
borrowed=""
restore() {
    rm -f /run/frogdash-wifi.lock
    [ -n "$borrowed" ] || return 0
    nmcli con down "$borrowed" >/dev/null 2>&1
    # The scan list is stale after another network; rescan, and retry while the dash cam wakes.
    for attempt in 1 2 3 4; do
        nmcli dev wifi rescan ifname "$device" >/dev/null 2>&1; sleep 5
        nmcli --wait 20 con up dashcam >/dev/null 2>&1 && return 0
    done
}
trap restore EXIT
if ! timeout 30 git -C $REPO fetch --quiet origin; then
    device=$(nmcli -g connection.interface-name con show dashcam 2>/dev/null)
    [ -n "$device" ] || device=$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="wifi"{print $1; exit}')
    report running "No internet: switching Wi-Fi from the dash cam to a saved network"
    touch /run/frogdash-wifi.lock   # Tell the Wi-Fi keeper the adapter is borrowed.
    nmcli con down dashcam >/dev/null 2>&1
    nmcli dev wifi rescan ifname "$device" >/dev/null 2>&1; sleep 4
    nmcli -t -f NAME,TYPE con show | awk -F: '$2=="802-11-wireless" && $1!="dashcam" && $1!="preconfigured"{print $1}' > /tmp/frogdash-wifi-names
    while IFS= read -r name; do
        if nmcli --wait 25 con up "$name" ifname "$device" >/dev/null 2>&1; then borrowed=$name; break; fi
    done < /tmp/frogdash-wifi-names
    rm -f /tmp/frogdash-wifi-names
    if [ -z "$borrowed" ] || ! timeout 90 git -C $REPO fetch --quiet origin; then
        report failed "No internet: no saved Wi-Fi network in range. Join one in Controls > Wi-Fi, or turn on your phone hotspot"
        exit 1
    fi
fi
newest=$(git -C $REPO rev-parse FETCH_HEAD 2>/dev/null)
if [ "$newest" != "$before" ] && [ "$newest" = "$(cat "$STATE/update-bad" 2>/dev/null)" ]; then
    report held "The newest version ($(short "$newest")) is the one that did not start last time. Staying on this one until a newer version is published"
    exit 1
fi
if ! out=$(git -C $REPO merge --ff-only --quiet FETCH_HEAD 2>&1); then
    report failed "Could not fast-forward (local changes on the Pi?). Update by hand with git pull"; exit 1
fi
after=$(git -C $REPO rev-parse HEAD)
if [ "$before" = "$after" ]; then
    install_helpers
    report current "Already up to date$added"; exit 0
fi
sync_units
changes=$(git -C $REPO rev-list --count "$before..$after")
echo "$before" > "$STATE/update-previous"
report running "Updated ($changes changes). Restarting the dash and checking it"
restart_dash
if healthy $had_screen; then
    rm -f "$STATE/update-bad"
    install_helpers
    report updated "Updated ($changes changes). The dash restarted and passed its check$added"; exit 0
fi

# The new version is not usable: keep the evidence, then put the old one back.
journalctl -u frogdash.service -n 80 --no-pager > "$STATE/update-failure.log" 2>&1
chmod 644 "$STATE/update-failure.log" 2>/dev/null
echo "$after" > "$STATE/update-bad"
rm -f "$STATE/update-previous"
failed=$(short "$after"); reason=$why
report running "Version $failed did not start properly ($reason). Going back to the previous version"
if git -C $REPO reset --keep --quiet "$before" && sync_units && restart_dash && healthy 0; then
    report rolledback "Update undone: version $failed did not start properly ($reason), so the dash went back to the version that worked"
else
    report failed "Version $failed did not start and going back failed too. From a laptop: sudo git -C $REPO reset --keep $(short "$before"), then sudo systemctl restart frogdash"
fi
exit 1
