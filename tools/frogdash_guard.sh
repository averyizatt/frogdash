#!/bin/sh
# The dash's last line of defence: puts back the last version that ran when the dash
# stops starting, with nobody there to do it. Run as root by frogdash-guard.service from
# a copy in /usr/local/lib/frogdash, which the Pi setup puts there only from a version
# that has started and answered, so a broken version cannot break the guard as well.
#
#  - The dash answering for GOOD_AFTER seconds: its version is remembered (last-good).
#  - The dash not answering for BAD_AFTER seconds, with no update or recovery running: the
#    remembered version is put back, the dash restarted, and the version that did not
#    start is not installed again (update-bad). Once for each version that fails.
#  - Nothing to go back to (the remembered version is the one failing): the dash is
#    restarted once, then left to the rescue screen (tools/frogdash_rescue.py).
#
# What it did is shown like an update's result (update-status.json) and in the event log.
# October 2026: an update left the dash unable to start, the key went off while the
# updater was putting the previous version back, and the screen stayed black until the
# Pi was reached with a keyboard. This is what does that by itself.
REPO=${FROGDASH_REPO:-/opt/frogdash}
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
UNITS=${FROGDASH_UNITS:-/etc/systemd/system}
BUSY=${FROGDASH_BUSY:-/run/frogdash-busy}
PORT=$(sed -n 's/.*--port[ =]\([0-9][0-9]*\).*/\1/p' /etc/default/frogdash 2>/dev/null | tail -n 1)
URL=${FROGDASH_HEALTH_URL:-http://127.0.0.1:${PORT:-8080}/health}
GOOD_AFTER=${FROGDASH_GUARD_GOOD_AFTER:-120}
BAD_AFTER=${FROGDASH_GUARD_BAD_AFTER:-150}
TICK=${FROGDASH_GUARD_TICK:-5}
ROUNDS=${FROGDASH_GUARD_ROUNDS:-0}   # 0: for ever (tests run a few)
GOOD=$STATE/last-good

probe() {
    if command -v curl >/dev/null 2>&1; then curl -fsS -m 3 "$URL" >/dev/null 2>&1
    else python3 -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=3)' "$URL" >/dev/null 2>&1
    fi
}
short() { git -C "$REPO" rev-parse --short "$1" 2>/dev/null; }
clean() { printf '%s' "$1" | tr -cd 'A-Za-z0-9 .,:;()/_+-' | cut -c1-240; }
report() {  # state, message: shown on the dash like an update's result
    printf '{"state":"%s","message":"%s","version":"%s","previous":"","time":%s}\n' "$1" "$(clean "$2")" \
        "$(short HEAD)" "$(date +%s)" > "$STATE/update-status.json.tmp" &&
        chmod 644 "$STATE/update-status.json.tmp" && mv "$STATE/update-status.json.tmp" "$STATE/update-status.json"
    mkdir -p "$STATE/events" 2>/dev/null
    printf '{"t":%s,"level":"error","area":"update","text":"%s"}\n' "$(date +%s)" "$(clean "$2")" \
        >> "$STATE/events/$(date -u +%Y-%m-%d).jsonl" 2>/dev/null
    echo "frogdash-guard: $2"
}
sync_units() {  # The unit files of the version put back, for those that are installed.
    changed=0
    for unit in "$REPO"/hardware/systemd/*.service "$REPO"/hardware/systemd/*.path; do
        [ -f "$unit" ] || continue
        target=$UNITS/$(basename "$unit")
        if [ -f "$target" ] && ! cmp -s "$unit" "$target"; then cp "$unit" "$target"; changed=1; fi
    done
    [ $changed = 1 ] && systemctl daemon-reload
    return 0
}
busy() {  # An update or a recovery is running: it is in charge.
    systemctl is-active --quiet frogdash-update.service 2>/dev/null && return 0
    [ -f "$BUSY" ] && [ -n "$(find "$BUSY" -mmin -20 2>/dev/null)" ]
}

recover() {
    head=$(git -C "$REPO" rev-parse HEAD 2>/dev/null) || return 0
    good=$(cat "$GOOD" 2>/dev/null)
    if [ -z "$good" ] || [ "$head" = "$good" ]; then
        # This is the version that last ran: no code to go back to. Restart it once (it
        # may have hung, or something it needs came back); after that the rescue screen
        # shows why, with what can be done.
        if [ "$restarted" != "$head" ]; then
            restarted=$head
            report failed "The dash stopped answering. Restarted it; if it stays down the rescue screen shows why"
            systemctl restart frogdash.service
        fi
        return 0
    fi
    [ "$head" = "$(cat "$STATE/guard-tried" 2>/dev/null)" ] && return 0   # Already went back from this one
    touch "$BUSY"
    echo "$head" > "$STATE/guard-tried"
    echo "$head" > "$STATE/update-bad"   # The updater does not install it again; a newer one is
    journalctl -u frogdash.service -n 80 --no-pager > "$STATE/update-failure.log" 2>&1
    chmod 644 "$STATE/update-failure.log" 2>/dev/null
    if git -C "$REPO" reset --keep --quiet "$good" 2>/dev/null || git -C "$REPO" reset --hard --quiet "$good" 2>/dev/null; then
        rm -f "$STATE/update-previous"
        sync_units
        systemctl restart frogdash.service
        report rolledback "Recovered by itself: version $(short "$head") did not start, so the dash went back to $(short "$good"), the last version that ran. Update now installs a newer one when there is one"
    else
        report failed "Version $(short "$head") does not start and going back to $(short "$good") failed. The rescue screen has what can be done"
    fi
    rm -f "$BUSY"
}

up=0; down=0; round=0; restarted=""
while [ "$ROUNDS" = 0 ] || [ $round -lt "$ROUNDS" ]; do
    round=$((round + 1))
    sleep "$TICK"
    if busy; then up=0; down=0; continue; fi
    if probe; then
        up=$((up + TICK)); down=0; restarted=""
        if [ $up -ge "$GOOD_AFTER" ]; then
            head=$(git -C "$REPO" rev-parse HEAD 2>/dev/null)
            if [ -n "$head" ] && [ "$head" != "$(cat "$GOOD" 2>/dev/null)" ]; then
                echo "$head" > "$GOOD.tmp" && mv "$GOOD.tmp" "$GOOD"
                rm -f "$STATE/guard-tried"
            fi
        fi
    else
        down=$((down + TICK)); up=0
        if [ $down -ge "$BAD_AFTER" ]; then recover; down=0; fi
    fi
done
exit 0
