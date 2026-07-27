#!/bin/bash
# Daily snapshot runner. Fails loudly: if collection doesn't produce a file,
# nothing gets committed and the script exits non-zero.
#
#   ./run_collect.sh            -> data/surface_YYYY-MM-DD.csv
#   ./run_collect.sh pre        -> data/surface_YYYY-MM-DD_pre.csv
set -uo pipefail

REPO=/Users/kendrichsu/vol-surface
PY=$REPO/venv/bin/python
LOG=$REPO/collect.log

cd "$REPO" || exit 1

LABEL="${1:-}"
if [ -n "$LABEL" ]; then
    SUFFIX="_$LABEL"
else
    SUFFIX=""
fi

DATE=$(date +%Y-%m-%d)
EXPECTED="data/surface_${DATE}${SUFFIX}.csv"

{
    echo "=== $(date) : starting collection ${LABEL:-daily} ==="
} >> "$LOG"

# Deliberately NOT an array. macOS ships bash 3.2, where expanding an empty
# array ("${ARGS[@]}" with ARGS=()) under `set -u` aborts with "unbound
# variable". The no-label path is exactly what the daily 3pm job uses, so an
# array here would break the unlabeled run while the labeled one worked.
if [ -n "$LABEL" ]; then
    "$PY" collect.py --label "$LABEL" >> "$LOG" 2>&1
    RC=$?
else
    "$PY" collect.py >> "$LOG" 2>&1
    RC=$?
fi

if [ "$RC" -ne 0 ]; then
    echo "$(date): collect.py FAILED rc=$RC (see $LOG) — nothing committed" | tee -a "$LOG"
    exit 1
fi

# collect.py exits 0 on weekends without writing a file; that's not an error.
if [ ! -f "$EXPECTED" ]; then
    echo "$(date): no file at $EXPECTED (weekend/skip?) — nothing committed" | tee -a "$LOG"
    exit 0
fi

git add data/
if git diff --cached --quiet; then
    echo "$(date): $EXPECTED unchanged — nothing to commit" | tee -a "$LOG"
    exit 0
fi

git commit -m "Auto: daily snapshot ${DATE}${SUFFIX:+ ($LABEL)}" >> "$LOG" 2>&1

# retry push with backoff — the 7/15 outage lost a snapshot to a dropped link
for delay in 0 2 4 8 16; do
    [ "$delay" -gt 0 ] && sleep "$delay"
    if git push -u origin HEAD >> "$LOG" 2>&1; then
        echo "$(date): pushed ${DATE}${SUFFIX}" | tee -a "$LOG"
        exit 0
    fi
done

echo "$(date): commit succeeded but PUSH FAILED after retries" | tee -a "$LOG"
exit 1
