#!/bin/sh
# Bring can0 back for the dash. Run as root by frogdash-canreset.service, which starts
# when the dash leaves a request in /var/lib/frogdash/can-request (nothing received for
# a while with the key on: hardware/frogdash/canwatch.py), or by hand:
#   sudo sh /opt/frogdash/tools/frogdash_can.sh
# The one thing it does is restart frogdash-can.service, which takes can0 down and up
# again at 500 kbit/s. The result is written for the dash to record.
STATE=${FROGDASH_STATE:-$(readlink -f /var/lib/frogdash 2>/dev/null || echo /var/lib/frogdash)}
STATUS=$STATE/can-status.json
rm -f "$STATE/can-request"

report() {  # result, message
    text=$(printf '%s' "$2" | tr -cd 'A-Za-z0-9 .,:;()/_+-' | cut -c1-240)
    printf '{"action":"reset","result":"%s","message":"%s","time":%s}\n' "$1" "$text" "$(date +%s)" > "$STATUS.tmp"
    chmod 644 "$STATUS.tmp"; mv "$STATUS.tmp" "$STATUS"
}
if ! ip link show can0 >/dev/null 2>&1; then
    report failed "can0 is missing: the CAN module's driver did not load"
    exit 1
fi
if systemctl restart frogdash-can.service >/dev/null 2>&1; then
    report ok "can0 taken down and up again"
else
    report failed "frogdash-can.service did not start again"
    exit 1
fi
exit 0
