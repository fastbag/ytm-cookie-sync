#!/usr/bin/with-contenv sh
# Prepare data directories and permissions, then start the service.
set -e
mkdir -p /data/chromium
chown -R chrome:chrome /data/chromium
chmod 700 /data/chromium
# /data traversable only (711) so the browser user "chrome" reaches its profile;
# all other files stay root-only (600).
chmod 711 /data
for f in /data/options.json /data/state.json; do
  [ -f "$f" ] && chown root:root "$f" && chmod 600 "$f"
done
if ! su-exec chrome sh -c 'touch /data/chromium/.write_test && rm /data/chromium/.write_test'; then
  echo "ERROR: browser profile /data/chromium is not writable for user chrome" >&2
fi
cp /app/index.html /usr/share/novnc/index.html
exec python3 -u /app/ytm_sync.py
