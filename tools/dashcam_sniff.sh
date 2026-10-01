#!/bin/sh
# Record what the Viidure phone app sends to your own Wi-Fi dash cam, so the dash can copy it.
#
# The Pi's USB Wi-Fi adapter listens on the camera's channel while your phone uses the
# app; the capture is then decrypted with the camera's own Wi-Fi name and password.
# Needs an adapter that supports monitor mode. Usage (on the Pi, dash cam connection up):
#
#   sudo sh tools/dashcam_sniff.sh [interface] [ssid] [password]
#
# Defaults: wlan1, DC-37BB0BD3, 12345678. Output: /tmp/dashcam.pcap (raw) and
# /tmp/dashcam-dec.pcap (decrypted) plus a summary of the app's requests.
set -eu
IF=${1:-wlan1}
SSID=${2:-DC-37BB0BD3}
PASS=${3:-12345678}

[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
for tool in iw tcpdump airdecap-ng tshark; do
    command -v "$tool" >/dev/null || { echo "Installing capture tools..."; DEBIAN_FRONTEND=noninteractive apt-get install -y iw tcpdump aircrack-ng tshark >/dev/null; break; }
done

PHY=$(iw dev "$IF" info | awk '/wiphy/ {print "phy" $2}')
if ! iw phy "$PHY" info | sed -n '/Supported interface modes/,/:$/p' | grep -q '\* monitor'; then
    echo "This adapter ($IF) does not support monitor mode; a capture is not possible with it."
    exit 2
fi

# Learn the camera's channel from the current connection.
INFO=$(iw dev "$IF" info)
FREQ=$(echo "$INFO" | sed -n 's/.*channel [0-9]* (\([0-9]*\) MHz).*/\1/p')
WIDTH=$(echo "$INFO" | sed -n 's/.*width: \([0-9]*\) MHz.*/\1/p')
CENTER=$(echo "$INFO" | sed -n 's/.*center1: \([0-9]*\) MHz.*/\1/p')
[ -n "$FREQ" ] || { echo "Connect $IF to the dash cam first (sudo nmcli con up dashcam)"; exit 3; }
echo "Camera is on $FREQ MHz, width ${WIDTH:-20} MHz"

restore() {
    ip link set "$IF" down 2>/dev/null || true
    iw dev "$IF" set type managed 2>/dev/null || true
    ip link set "$IF" up 2>/dev/null || true
    nmcli dev set "$IF" managed yes 2>/dev/null || true
    nmcli con up dashcam >/dev/null 2>&1 || true
}
trap restore EXIT

nmcli con down dashcam >/dev/null 2>&1 || true
nmcli dev set "$IF" managed no
ip link set "$IF" down
iw dev "$IF" set type monitor
ip link set "$IF" up
case "${WIDTH:-20}" in
    80|160) iw dev "$IF" set freq "$FREQ" "$WIDTH" "$CENTER" ;;
    40) iw dev "$IF" set freq "$FREQ" HT40+ 2>/dev/null || iw dev "$IF" set freq "$FREQ" HT40- ;;
    *) iw dev "$IF" set freq "$FREQ" ;;
esac

rm -f /tmp/dashcam.pcap /tmp/dashcam-dec.pcap
tcpdump -i "$IF" -U -w /tmp/dashcam.pcap 2>/dev/null &
DUMP=$!
cat <<EOF

Recording. On your iPhone now:
  1. Settings > Wi-Fi: turn Wi-Fi OFF, then ON, and join $SSID
     (this lets the capture see the connection's encryption keys)
  2. Open Viidure, open the live view and watch it for about 20 seconds
     (switch to the rear camera once if you have it), then close the app.
Press Enter here when done.
EOF
read _
kill "$DUMP"; wait "$DUMP" 2>/dev/null || true

echo "Decrypting..."
airdecap-ng -e "$SSID" -p "$PASS" /tmp/dashcam.pcap | tail -8
[ -s /tmp/dashcam-dec.pcap ] || { echo "Nothing decrypted: rejoin the camera's Wi-Fi on the phone during the recording."; exit 4; }

echo
echo "== Connections to the camera"
tshark -r /tmp/dashcam-dec.pcap -q -z conv,tcp 2>/dev/null | sed -n '1,25p'
echo "== Phone app HTTP requests"
tshark -r /tmp/dashcam-dec.pcap -Y http.request -T fields -e http.request.method -e http.request.uri 2>/dev/null | uniq | head -60
echo "== First bytes the app sent to each non-HTTP port"
tshark -r /tmp/dashcam-dec.pcap -Y 'tcp.len>0 && !http && ip.dst==192.168.169.1' -T fields -e tcp.dstport -e tcp.payload 2>/dev/null \
    | awk '!seen[$1]++ {print $1, substr($2, 1, 160)}' | head -10
echo
echo "Done. Send me this summary; keep /tmp/dashcam-dec.pcap for details."
