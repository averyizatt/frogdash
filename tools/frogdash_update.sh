#!/bin/sh
# Update the dash from GitHub and restart it. Run as root by frogdash-update.service,
# which starts when the dash writes /var/lib/frogdash/update-request (the Update button),
# or by hand:
#   sudo sh /opt/frogdash/tools/frogdash_update.sh            update to the newest version
#   sudo sh /opt/frogdash/tools/frogdash_update.sh rollback   return to the version before the last update
# Only fast-forwards the installed branch; local changes or a failed pull leave the
# running version untouched. The result is written for the dash to show.
#
# Before anything changes, the new version is started in a scratch copy, on a port of
# its own and with no CAN, GPS or helpers, while the running dash carries on (trial). One
# that does not answer there is never switched to: the dash stays as it is and the reason
# is shown (October 2026: a version that needed a package the Pi did not have yet left
# the screen black).
#
# A new version then has to prove itself after the restart: the service must come up, answer
# on HTTP and stay up, and the screen must reconnect if it was connected before. If it
# does not, the previous version is put back and restarted, and that commit is not
# installed again (a newer one is). The failed start is kept in update-failure.log.
#
# While this runs, /run/frogdash-busy holds off the PiSugar shutdown (hardware/power/
# monitor.py), so turning the key off cannot stop it half way. If power is lost anyway,
# the recovery guard (tools/frogdash_guard.sh) finishes the job at the next start.
#
# Whatever else the version needs on the Pi (root helpers, packages, service settings)
# is done by tools/frogdash_setup.sh, run from here as root after every update and on
# "Already up to date", so nothing ever needs typing over SSH. It is always the new
# version's script that runs. The dash asks for it alone with the request word 'setup'.
REPO=${FROGDASH_REPO:-/opt/frogdash}
BUSY=${FROGDASH_BUSY:-/run/frogdash-busy}
VENV_PY=${FROGDASH_VENV_PY:-$REPO/.venv/bin/python}
TRIAL_PORT=${FROGDASH_TRIAL_PORT:-18781}
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
UNITS=${FROGDASH_UNITS:-/etc/systemd/system}
STATUS=$STATE/update-status.json
PORT=$(sed -n 's/.*--port[ =]\([0-9][0-9]*\).*/\1/p' /etc/default/frogdash 2>/dev/null | tail -n 1)
URL=${FROGDASH_HEALTH_URL:-http://127.0.0.1:${PORT:-8080}/health}
action=${1:-$(cat "$STATE/update-request" 2>/dev/null)}
rm -f "$STATE/update-request"
touch "$BUSY" 2>/dev/null   # Holds off the PiSugar shutdown until this is done
trap 'rm -f "$BUSY"' EXIT
# Stopped: Cancel on the dash (frogdash-update-cancel.service leaves update-cancel and stops this),
# its hour up, or the Pi shutting down. Say so, or 'running' would stay on the screens; the dash
# also stops believing a 'running' with no $BUSY (connectivity.current_update). Once the result
# is written (finished), only the upload after it is cut short.
mode=update; finished=""
stopped() {
    if [ -z "$finished" ]; then
        if [ -f "$STATE/update-cancel" ]; then report cancelled "Cancelled. Update now starts again"
        else report failed "Stopped before it finished (the Pi was turning off, or it ran over an hour). Update now runs it again"
        fi
    fi
    exit 1
}
trap stopped TERM INT

short() { git -C $REPO rev-parse --short "$1" 2>/dev/null; }
report() {  # state, message. The mode tells the dash a start-up setup (which Update now may stop) from an update.
    printf '{"state":"%s","message":"%s","version":"%s","previous":"%s","time":%s,"mode":"%s"}\n' "$1" "$2" \
        "$(short HEAD)" "$(short "$(cat "$STATE/update-previous" 2>/dev/null)")" "$(date +%s)" "$mode" > "$STATUS.tmp"
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
    for unit in $REPO/hardware/systemd/*.service $REPO/hardware/systemd/*.path $REPO/hardware/systemd/*.timer; do
        [ -f "$unit" ] || continue
        target=$UNITS/$(basename "$unit")
        if [ -f "$target" ] && ! cmp -s "$unit" "$target"; then cp "$unit" "$target"; changed=1; fi
    done
    [ $changed = 1 ] && systemctl daemon-reload
    return 0
}
setup() {  # $1 = online when GitHub was just reached. Leaves what it did in $note.
    note=""
    [ -f "$REPO/tools/frogdash_setup.sh" ] || return 0
    sync_units  # Also on "Already up to date": an older updater may have left the unit files behind.
    note=$(FROGDASH_REPO=$REPO FROGDASH_STATE=$STATE FROGDASH_UNITS=$UNITS sh "$REPO/tools/frogdash_setup.sh" $1 2>/dev/null | grep '^Set up: ' | tail -n 1 | tr -cd 'A-Za-z0-9 .,:()/_-')
    [ -z "$note" ] || note=". $note"
    return 0
}
upload() {  # Diagnostics and the newest drive to the owner's private repository, while online.
    said=""
    [ -f "$REPO/tools/frogdash_upload.py" ] || return 0
    said=$(FROGDASH_STATE=$STATE FROGDASH_REPO=$REPO FROGDASH_UNITS=$UNITS timeout 600 python3 "$REPO/tools/frogdash_upload.py" 2>/dev/null | tail -n 1 | tr -cd 'A-Za-z0-9 .,:;()/_-')
    return 0
}
finish() {  # state, message: the result first (the buttons work again), then the upload, which adds what it did
    report "$1" "$2"; finished=1
    upload
    [ -z "$said" ] || report "$1" "$2. $said"
}
packages() {  # $1 = commit. Packages it adds to requirements.lock, before it is tried.
    # Added to the dash's environment, which the running version keeps working with. The
    # dash also starts without them (the setup step installs them otherwise), but then a
    # feature waits for the setup. Best effort: a failure here is not a failed update.
    git -C $REPO diff --quiet "$before" "$1" -- requirements.lock 2>/dev/null && return 0
    [ -x "$VENV_PY" ] || return 0
    lock=$(mktemp) || return 0
    git -C $REPO show "$1:requirements.lock" > "$lock" 2>/dev/null || { rm -f "$lock"; return 0; }
    report running "Installing the Python packages this version adds"
    timeout 900 "$VENV_PY" -m pip install --quiet --disable-pip-version-check -r "$lock" >/dev/null 2>&1
    rm -f "$lock"
    return 0
}
trial_wait() {  # $1 = pid, $2 = seconds: 0 once the trial copy answers; 1 if it stops or the time runs out
    "$python" -c '
import os, sys, time, urllib.request
pid, deadline = int(sys.argv[1]), time.monotonic() + float(sys.argv[2])
while time.monotonic() < deadline:
    try:
        urllib.request.urlopen(sys.argv[3], timeout=2).read()
        sys.exit(0)
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        sys.exit(1)          # It stopped: an error at start
    time.sleep(.5)
sys.exit(1)' "$1" "$2" "http://127.0.0.1:$TRIAL_PORT/health" >/dev/null 2>&1
}
trial() {  # $1 = commit. Starts it from a scratch copy; 1 with the reason in $why if it does not answer.
    git -C $REPO cat-file -e "$1:hardware/frogdash/server.py" 2>/dev/null || return 0   # Not the dash: nothing to try
    work=$(mktemp -d "${TMPDIR:-/var/tmp}/frogdash-trial.XXXXXX") || return 0         # No room to try: as before
    # The whole version, as it will be checked out: the dash reads files from all over it.
    if ! git -C $REPO archive "$1" 2>/dev/null | tar -x -C "$work" 2>/dev/null; then
        rm -rf "$work"; return 0
    fi
    python=$VENV_PY; [ -x "$python" ] || python=python3
    mkdir -p "$work/data"
    report running "Trying the new version before switching to it"
    # No CAN interface, GPS, camera, recording or helpers: it only has to start and answer.
    (cd "$work" && exec "$python" -m hardware.frogdash.server --interface frogdash-trial --port "$TRIAL_PORT" \
        --data-dir "$work/data" --race-file "$work/data/race.json" --hotspot-socket "$work/no-helper.sock") \
        > "$work/start.log" 2>&1 &
    pid=$!
    answered=0
    trial_wait $pid ${FROGDASH_TRIAL_WAIT:-60} || answered=1
    kill $pid 2>/dev/null; wait $pid 2>/dev/null
    if [ $answered != 0 ]; then
        why=$(grep -E '[A-Za-z]+(Error|Exception)' "$work/start.log" | tail -n 1 | tr -cd 'A-Za-z0-9 .,:;()/_-' | cut -c1-160)
        [ -n "$why" ] || why="it did not answer within ${FROGDASH_TRIAL_WAIT:-60} s"
        { echo "Trial start of $1:"; cat "$work/start.log"; } > "$STATE/update-failure.log" 2>/dev/null
        chmod 644 "$STATE/update-failure.log" 2>/dev/null
    fi
    rm -rf "$work"
    return $answered
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

if [ "$action" = setup ] || [ "$action" = helpers ]; then  # From the dash at start-up. Nothing else changes.
    # Shown while it runs (a first install takes a while, and Update now waits for it); the
    # last update's result comes back afterwards.
    last=""; mode=setup
    [ -f "$STATUS" ] && cp "$STATUS" "$STATUS.last" && last=1
    report running "Finishing the Pi setup for this version (a first-time install can take several minutes)"
    setup
    if [ -n "$last" ]; then mv "$STATUS.last" "$STATUS"; else report current "Pi setup finished$note"; fi
    exit 0
fi
if [ "$action" = upload ]; then  # Send now, or GitHub just connected: the reports only.
    [ -f "$REPO/tools/frogdash_upload.py" ] && FROGDASH_STATE=$STATE FROGDASH_REPO=$REPO FROGDASH_UNITS=$UNITS \
        timeout 1200 python3 "$REPO/tools/frogdash_upload.py" >/dev/null 2>&1
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
# Room for the new version and its trial copy first: a full SD card fails half way otherwise.
free=$(df -Pk "$REPO" 2>/dev/null | awk 'NR==2 {print int($4 / 1024)}')
if [ -n "$free" ] && [ "$free" -lt "${FROGDASH_MIN_FREE_MB:-300}" ]; then
    report failed "Only $free MB free on the Pi: an update needs ${FROGDASH_MIN_FREE_MB:-300} MB. Delete old drives or dash cam clips, then try again"
    exit 1
fi
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
trap 'restore; rm -f "$BUSY"' EXIT
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
if [ "$newest" != "$before" ]; then
    packages "$newest"
    if ! trial "$newest"; then
        echo "$newest" > "$STATE/update-bad"
        finish failed "Version $(short "$newest") would not start ($why), so the dash stayed on this version: nothing was changed"
        exit 1
    fi
fi
if ! out=$(git -C $REPO merge --ff-only --quiet FETCH_HEAD 2>&1); then
    report failed "Could not fast-forward (local changes on the Pi?). Update by hand with git pull"; exit 1
fi
after=$(git -C $REPO rev-parse HEAD)
if [ "$before" = "$after" ]; then
    report running "Already up to date. Checking the Pi setup"
    setup online
    finish current "Already up to date$note"; exit 0
fi
sync_units
changes=$(git -C $REPO rev-list --count "$before..$after")
echo "$before" > "$STATE/update-previous"
report running "Updated ($changes changes). Restarting the dash and checking it"
restart_dash
if healthy $had_screen; then
    rm -f "$STATE/update-bad"
    report running "Updated ($changes changes) and checked. Finishing the Pi setup"
    setup online
    finish updated "Updated ($changes changes). The dash restarted and passed its check$note"; exit 0
fi

# The new version is not usable: keep the evidence, then put the old one back.
journalctl -u frogdash.service -n 80 --no-pager > "$STATE/update-failure.log" 2>&1
chmod 644 "$STATE/update-failure.log" 2>/dev/null
echo "$after" > "$STATE/update-bad"
rm -f "$STATE/update-previous"
failed=$(short "$after"); reason=$why
report running "Version $failed did not start properly ($reason). Going back to the previous version"
note=""
if git -C $REPO reset --keep --quiet "$before" && sync_units && restart_dash && healthy 0; then
    # The failed start's evidence goes up with the diagnostics.
    finish rolledback "Update undone: version $failed did not start properly ($reason), so the dash went back to the version that worked$note"
else
    report failed "Version $failed did not start and going back failed too. From a laptop: sudo git -C $REPO reset --keep $(short "$before"), then sudo systemctl restart frogdash"
fi
exit 1
