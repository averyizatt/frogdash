#!/bin/sh
# Read what the dash screen needs at start into memory, early in boot, while Linux and
# the screen session are still starting (frogdash-warm.service, after the root file
# system is mounted). Every key-on is a cold boot: a warm Chromium drew the dash 4 s
# after launch, a cold one 11.5 s, and most of the difference is reading it off the SD
# card (boot reports, October 2026). Reading those files now, before Cage asks for them,
# moves that wait to a time when nothing is waiting for it.
#
# Read-only: it changes nothing on the Pi. It does nothing with less than about 900 MB
# of memory free, and a failure only means the browser starts as it did before.
avail=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo 2>/dev/null)
[ "${avail:-0}" -ge "${FROGDASH_WARM_MIN_MB:-900}" ] || { echo "frogdash-warm: ${avail:-?} MB free, skipped"; exit 0; }

read_files() {  # Each file once, in the order given; missing ones are skipped
    while IFS= read -r file; do
        [ -f "$file" ] && cat "$file" > /dev/null 2>&1
    done
}

start=$(cut -d' ' -f1 /proc/uptime)
browser=$(command -v chromium 2>/dev/null || command -v chromium-browser 2>/dev/null)
dir=/usr/lib/chromium
[ -d "$dir" ] || dir=$(dirname "$(readlink -f "$browser" 2>/dev/null)")
{
    # The browser itself first: it is what the screen waits for.
    for name in chromium chrome chromium-browser; do [ -f "$dir/$name" ] && echo "$dir/$name"; done
    # Its data files (only the English locale), then the libraries it is linked with.
    find "$dir" -maxdepth 1 -type f \( -name '*.pak' -o -name '*.dat' -o -name '*.bin' -o -name '*.so*' \) 2>/dev/null
    for locale in "$dir"/locales/en-US.pak "$dir"/locales/en-US.pak.info; do echo "$locale"; done
    ldd "$dir/chromium" 2>/dev/null | awk '/=> \// {print $3}'
    # The compositor and the launcher.
    command -v cage
    ldd "$(command -v cage)" 2>/dev/null | awk '/=> \// {print $3}'
    # The dash's own page.
    find "${FROGDASH_REPO:-/opt/frogdash}/hardware/ui" -maxdepth 1 -type f 2>/dev/null
} | read_files

# The screen user's browser profile, with its stored compiled page code, if it is small.
for profile in /home/*/.config/frogdash-chromium; do
    [ -d "$profile" ] || continue
    size=$(du -sm "$profile" 2>/dev/null | cut -f1)
    [ "${size:-999}" -le 300 ] && find "$profile" -type f -size -20M 2>/dev/null | read_files
done
echo "frogdash-warm: read the screen's files from boot+${start}s to boot+$(cut -d' ' -f1 /proc/uptime)s"
exit 0
