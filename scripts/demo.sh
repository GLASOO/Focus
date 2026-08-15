#!/usr/bin/env bash
# Focus Agent — 60-second demo, no model required.
# Watches the machine take its first breaths with the dummy backend.
set -e
cd "$(dirname "$0")/.."
# prefer the repo venv, then PATH
PY=""
for cand in .venv/bin/python .venv/bin/python3 "$(command -v python)" "$(command -v python3)"; do
  [ -n "$cand" ] && [ -x "$cand" ] && PY="$cand" && break
done
[ -z "$PY" ] && { echo "❌ no python found"; exit 1; }
if ! "$PY" -c "import loguru" 2>/dev/null; then
  echo "❌ missing deps. Run first:  python3 -m venv .venv && . .venv/bin/activate && pip install loguru numpy"
  exit 1
fi

DB="$(mktemp -d)/focus_demo.db"
echo "🫁 demo DB: $DB"
echo "🫁 breathing for 20 seconds (dummy backend)..."

FOCUS_BACKEND=dummy FOCUS_DB="$DB" "$PY" -m focus.main &
PID=$!
sleep 20
kill "$PID" 2>/dev/null || true

echo
echo "🧠 thoughts landed:"
"$PY" - "$DB" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
try:
    n = c.execute("SELECT COUNT(*) FROM thought_log").fetchone()[0]
    print(f"   {n} thoughts")
    for r in c.execute(
            "SELECT substr(brief,1,60) FROM nodes ORDER BY rowid DESC LIMIT 3"):
        print("   ·", r[0] or "(breath)")
except sqlite3.OperationalError:
    print("   (demo DB empty — check python deps: pip install loguru numpy)")
PY
echo
echo "此机不停。Next: point FOCUS_API_BASE at a real model and let it live."
