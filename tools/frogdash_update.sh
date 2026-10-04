#!/bin/sh
# Update the dash from GitHub and restart it. Run as root by frogdash-update.service,
# which starts when the dash writes /var/lib/frogdash/update-request (the Update button),
# or by hand: sudo sh /opt/frogdash/tools/frogdash_update.sh
# Only fast-forwards the installed branch; local changes or a failed pull leave the
# running version untouched. The result is written for the dash to show.
REPO=/opt/frogdash
STATE=$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)
STATUS=$STATE/update-status.json
rm -f "$STATE/update-request"

report() {  # state, message
    printf '{"state":"%s","message":"%s","version":"%s","time":%s}\n' "$1" "$2" \
        "$(git -C $REPO rev-parse --short HEAD 2>/dev/null)" "$(date +%s)" > "$STATUS.tmp"
    chmod 644 "$STATUS.tmp"; mv "$STATUS.tmp" "$STATUS"
}

report running "Checking for updates"
before=$(git -C $REPO rev-parse HEAD) || { report failed "Not a git checkout: $REPO"; exit 1; }
if ! timeout 90 git -C $REPO fetch --quiet origin; then
    report failed "No internet: connect the Pi to Wi-Fi (phone hotspot) and try again"; exit 1
fi
if ! out=$(git -C $REPO merge --ff-only --quiet FETCH_HEAD 2>&1); then
    report failed "Could not fast-forward (local changes on the Pi?). Update by hand with git pull"; exit 1
fi
after=$(git -C $REPO rev-parse HEAD)
if [ "$before" = "$after" ]; then
    report current "Already up to date"; exit 0
fi
# Refresh only the unit files that are already installed.
changed=0
for unit in $REPO/hardware/systemd/*.service $REPO/hardware/systemd/*.path; do
    [ -f "$unit" ] || continue
    target=/etc/systemd/system/$(basename "$unit")
    if [ -f "$target" ] && ! cmp -s "$unit" "$target"; then cp "$unit" "$target"; changed=1; fi
done
[ $changed = 1 ] && systemctl daemon-reload
count=$(git -C $REPO rev-list --count "$before..$after")
report updated "Updated ($count changes). Restarting the dash"
systemctl restart frogdash.service
systemctl try-restart 'frogdash-console@*.service' 2>/dev/null
exit 0
