#!/usr/bin/env bash
# run_one.sh <arm> <video_id> <run#> — one summarize call for a summarize A/B (see docs/m0-ab.md).
# Outputs go to $AB_OUT (default .cache/ab/run, gitignored) — never into tracked paths.
# Writes <arm>/<id>.r<n>.json (raw CLI JSON) and <arm>/<id>.r<n>.md (the result text).
set -uo pipefail
ARM=$1 ID=$2 N=$3
AB="${AB_OUT:-/Users/ahdimel/code/smart_yt_consumer/.cache/ab/run}"
REPO=/Users/ahdimel/code/smart_yt_consumer
BUNDLE="$REPO/.cache/$ID.bundle.txt"
PROMPT="$(cat "$REPO/prompts/summarize.md")"
OUT="$AB/$ARM/$ID.r$N"
mkdir -p "$AB/$ARM" "$AB/empty"
SYS="You are a careful analyst. Follow the instructions in the user's message exactly."
run_capped(){ local secs=$1; shift; perl -e 'alarm shift; exec @ARGV' "$secs" "$@"; }

start=$(date +%s)
case "$ARM" in
  A)  # production as drain runs it (repo root, CLAUDE.md loaded), model/effort pinned
      cd "$REPO"
      run_capped 900 claude -p "$PROMPT" --output-format json --no-session-persistence \
        --model opus --effort high \
        --disallowed-tools "Bash,Edit,Write,Read,Glob,Grep,NotebookEdit,Task,Artifact,WebFetch,WebSearch" \
        < "$BUNDLE" > "$OUT.json" 2> "$OUT.err" ;;
  B|D) # lean: no tools, no settings, no MCP, short system prompt, empty cwd
      cd "$AB/empty"
      MODEL=opus; [[ $ARM == D ]] && MODEL=sonnet
      run_capped 900 claude -p "$PROMPT" --output-format json --no-session-persistence \
        --model "$MODEL" --effort high --tools "" --setting-sources "" --strict-mcp-config \
        --system-prompt "$SYS" \
        < "$BUNDLE" > "$OUT.json" 2> "$OUT.err" ;;
esac
rc=$?
python3 - "$OUT.json" "$OUT.md" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    open(sys.argv[2], 'w').write(d.get('result') or '')
except Exception as e:
    open(sys.argv[2], 'w').write('')
PY
echo "$(date '+%H:%M:%S') $ARM $ID r$N rc=$rc $(( $(date +%s) - start ))s $(wc -c < "$OUT.md" | tr -d ' ')B" >> "$AB/progress.log"
