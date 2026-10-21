#!/bin/sh
# exec keeps the same PID for systemd's logind activation helper.
read uptime rest < /proc/uptime
printf 'Frogdash kiosk: starting Cage (boot+%ss)\n' "$uptime"
exec /usr/bin/dbus-run-session -- /usr/bin/cage -s -m last -- /usr/bin/python3 /opt/frogdash/tools/launch_kiosk.py --wayland --dedicated-profile --allow-audio
