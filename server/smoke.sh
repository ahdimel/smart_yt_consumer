#!/usr/bin/env bash
# End-to-end smoke test of the server under real uvicorn, playing the worker with curl.
# Run from the repo root: server/smoke.sh. Uses a throwaway DB in a temp dir and port 8765.
set -u
SP="$(mktemp -d)"; echo "scratch: $SP"
export DB_PATH="$SP/smoke.db" WORKER_TOKEN=smoke-worker COOKIE_SECURE=0 PUBLIC_ORIGIN=http://127.0.0.1:8765
B=http://127.0.0.1:8765

LINK=$(server/.venv/bin/python -m server.cli invite --name Owner --email hello@ahdimel.com --admin)
echo "link: ${LINK%/*}/…"
server/.venv/bin/uvicorn server.app:create_app --factory --no-access-log --port 8765 > "$SP/uvicorn.log" 2>&1 &
PID=$!
for _ in $(seq 1 30); do curl -s -o /dev/null $B/healthz && break; sleep 0.2; done
TOK=${LINK##*/}

echo "invite: $(curl -s -o /dev/null -w '%{http_code} -> %{redirect_url}' "$B/u/$TOK")"
echo "submit: $(curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: application/json' \
  -d '{"url":"Watch https://youtu.be/dQw4w9WgXcQ?si=x"}' $B/api/requests)"
CLAIM=$(curl -s -X POST -H 'Authorization: Bearer smoke-worker' $B/worker/claim)
echo "claim: $CLAIM"
read -r JID LID < <(echo "$CLAIM" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["job_id"],d["lease_id"])')
python3 - "$LID" > "$SP/complete.json" <<'EOF'
import json, sys
print(json.dumps({'lease_id': sys.argv[1], 'md': open('out/2026-W40/6CAbZRpy4tQ.md').read(),
                  'usage': {'input_tokens': 40186, 'output_tokens': 12537},
                  'cost_usd': 0.65, 'model': 'claude-opus-5'}))
EOF
echo "complete: $(curl -s -H 'Authorization: Bearer smoke-worker' -H 'Content-Type: application/json' \
  --data @"$SP/complete.json" "$B/worker/jobs/$JID/complete")"
echo "resubmit (cache hit): $(curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: text/plain' \
  --data 'https://youtu.be/dQw4w9WgXcQ' $B/api/requests)"
echo "bad url: $(curl -s -H "Authorization: Bearer $TOK" -H 'Content-Type: text/plain' \
  --data 'https://vimeo.com/1' $B/api/requests)"
curl -s -H "Cookie: session=$TOK" $B/admin > "$SP/admin.html"
echo "admin bytes: $(wc -c < "$SP/admin.html"); content hits: $(grep -c -i -E 'youtube|dQw4w9WgXcQ|Putin|Anduril' "$SP/admin.html")"
curl -s -H "Cookie: session=$TOK" $B/admin/usage.json | python3 -c '
import sys, json
d = json.load(sys.stdin)
print("tokens 24h:", d["tokens_last_24h"], "| emails pending:", d["emails_pending"],
      "| requests:", [(r["status"], r["cache_hit"]) for r in d["requests"]])'
curl -s -o /dev/null -w 'css: %{http_code} %{content_type}\n' $B/static/app.css
kill $PID; wait $PID 2>/dev/null
echo '--- server log:'; cat "$SP/uvicorn.log"
grep -c -E 'youtube|dQw4w9WgXcQ|smoke-worker' "$SP/uvicorn.log" | sed 's/^/content or secret hits in log: /'
grep -c -F "$TOK" "$SP/uvicorn.log" | sed 's/^/token hits in log: /'
