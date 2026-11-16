#!/bin/bash
# Hourly Binance public-data fetch -> commit -> push. Scheduled from cron.
set -u
export PATH=/usr/local/bin:/usr/bin:/bin
DIR="$HOME/binance-data"
LOG="$DIR/fetch.log"
MAX_BYTES=1048576   # rotate fetch.log at 1 MB
KEEP=5              # keep fetch.log.1 .. fetch.log.5

cd "$DIR" || exit 1

# Only one run at a time; a second run exits immediately.
exec 9>"$DIR/.run.lock"
if ! flock -n 9; then
    echo "$(date -u +%FT%TZ) previous run still active, skipping" >>"$LOG"
    exit 0
fi

if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -ge "$MAX_BYTES" ]; then
    for i in $(seq $((KEEP - 1)) -1 1); do
        [ -f "$LOG.$i" ] && mv -f "$LOG.$i" "$LOG.$((i + 1))"
    done
    mv -f "$LOG" "$LOG.1"
fi
exec >>"$LOG" 2>&1

now() { date -u +%FT%TZ; }
echo "=== $(now) run start"

if ! python3 fetch_binance.py --years 4 --top 20; then
    echo "$(now) FETCH FAILED, nothing committed"
    exit 1
fi

git add -A
# meta.json is rewritten with a new timestamp every run; it alone is not a change.
if git diff --cached --quiet -- . ':(exclude)binance_data/meta.json'; then
    git reset -q
    git checkout -q -- binance_data/meta.json 2>/dev/null
    echo "$(now) no new data"
else
    newest_ms=$(for f in binance_data/*_1h.csv; do tail -n 1 "$f" | cut -d, -f1; done | sort -n | tail -n 1)
    newest=$(date -u -d "@$((newest_ms / 1000))" +%FT%TZ)
    git commit -q -m "$(now) newest candle $newest" || { echo "$(now) COMMIT FAILED"; exit 1; }
    echo "$(now) committed: $(git log -1 --format='%h %s')"
fi

# Push whenever there is anything the remote lacks (covers an earlier failed push).
if [ "$(git rev-parse HEAD 2>/dev/null)" != "$(git rev-parse -q --verify refs/remotes/origin/main 2>/dev/null)" ]; then
    if timeout 600 git push -q origin main; then
        echo "$(now) pushed $(git rev-parse --short HEAD)"
    else
        echo "$(now) PUSH FAILED"
        exit 1
    fi
fi
echo "=== $(now) run end"
