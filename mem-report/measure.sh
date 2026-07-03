#!/usr/bin/env bash
# Measure the trypurescript server's peak heap ("bytes maximum residency")
# for one (scenario, cache-mode, max-heap) combination.
#
# usage: measure.sh <scenario> <cold|warm> <maxheap e.g. 8G>
#
#   scenario  one of the directories under mem-report/scenarios/
#   cold      removes staging/.psci_modules before boot
#   warm      requires staging/.psci_modules to exist and be non-trivial
#             (it is produced by the cold run of the SAME scenario;
#              never reuse another scenario's cache)
#
# Environment overrides: BIN (server binary), SPAGO, PORT.
#
# The server is launched with +RTS -N2 -A128m -M<maxheap> -S<file>; the -S
# file receives the per-GC trace plus, on clean exit (SIGINT) or heap
# exhaustion, the standard RTS summary from which we parse
# "bytes maximum residency", "total memory in use", SPARKS, MUT/GC/Total.
# One /compile request is POSTed before shutdown to prove the environment
# actually loaded. Appends one JSON object per run to mem-report/results.json.
set -u

SCEN="${1:?scenario}"; MODE="${2:?cold|warm}"; MAXH="${3:?maxheap}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
STAGING="$ROOT/staging"
BIN="${BIN:-/Users/pete/Code/purescript/trypurescript/.stack-work/install/aarch64-osx/d4e7ad357244af6d2ed6bd049be0308ff7060cc108962bf242939e22a8526165/9.2.5/bin/trypurescript}"
SPAGO="${SPAGO:-spago}"
PORT="${PORT:-8081}"
TAG="$SCEN-$MODE-$MAXH"
SFILE="/tmp/mem-report-$TAG.S"
ERRFILE="/tmp/mem-report-$TAG.err"
OUTFILE="/tmp/mem-report-$TAG.out"
GLOBFILE="/tmp/mem-report-globs-$SCEN.txt"
TIMEOUT_S=1800

log() { echo "[measure $TAG] $*"; }

[ -d "$HERE/scenarios/$SCEN" ] || { log "no such scenario"; exit 1; }
[ -x "$BIN" ] || { log "binary not executable: $BIN"; exit 1; }

# refuse to run if something is already listening on the port
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  log "something already listening on $PORT; aborting"; exit 1
fi

cd "$STAGING"
cp "$HERE/scenarios/$SCEN/spago.yaml" spago.yaml
cp "$HERE/scenarios/$SCEN/spago.lock" spago.lock

# fetch any missing package sources into .spago/p/ (most are already there)
XDG_CACHE_HOME="$PWD/.spago-cache" "$SPAGO" fetch >/dev/null 2>&1 \
  || { log "spago fetch failed"; exit 1; }

# regenerate glob list per scenario; globs must reach the binary unexpanded
XDG_CACHE_HOME="$PWD/.spago-cache" "$SPAGO" sources 2>/dev/null > "$GLOBFILE"
NGLOBS=$(grep -c . "$GLOBFILE")
[ "$NGLOBS" -gt 100 ] || { log "suspiciously few globs ($NGLOBS)"; exit 1; }
log "$NGLOBS source globs"

# cache state = the cold/warm switch (server cache is .psci_modules, NOT output/)
if [ "$MODE" = cold ]; then
  rm -rf .psci_modules
else
  N=$(ls .psci_modules 2>/dev/null | wc -l | tr -d ' ')
  [ "${N:-0}" -gt 1000 ] || { log "warm mode needs populated .psci_modules (found ${N:-0})"; exit 1; }
fi

GLOBS=()
while IFS= read -r line; do [ -n "$line" ] && GLOBS+=("$line"); done < "$GLOBFILE"

rm -f "$SFILE" "$ERRFILE" "$OUTFILE"
START=$(date +%s)
"$BIN" +RTS -N2 -A128m -M"$MAXH" -S"$SFILE" -RTS "$PORT" "${GLOBS[@]}" \
  >"$OUTFILE" 2>"$ERRFILE" &
PID=$!
log "launched pid $PID (-M$MAXH, $MODE)"

PROGRAM='module Main where

import Prelude

import Effect (Effect)
import Effect.Console (log)
import Data.Array (range, filter, length)
import Data.Foldable (sum)

isEven :: Int -> Boolean
isEven n = mod n 2 == 0

main :: Effect Unit
main = do
  let xs = range 1 100
      evens = filter isEven xs
      total = sum evens
  log ("count: " <> show (length evens))
  log ("sum:   " <> show total)
'

# SIGINT occasionally gets lost when the RTS is idle; retry until it exits.
shutdown() {
  local i=0
  while kill -0 "$PID" 2>/dev/null && [ "$i" -lt 24 ]; do
    kill -INT "$PID" 2>/dev/null
    sleep 5
    i=$((i+1))
  done
  wait "$PID" 2>/dev/null
}

OUTCOME=""; BOOT="null"; COMPILE_OK=false
while :; do
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null
    if grep -qi "heap exhausted" "$ERRFILE" "$OUTFILE" "$SFILE" 2>/dev/null; then
      OUTCOME="heap-exhausted"
    else
      OUTCOME="died"
    fi
    log "process exited before serving: $OUTCOME"
    break
  fi
  if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    BOOT=$(( $(date +%s) - START ))
    # Settle before the first request: "bytes maximum residency" is only
    # sampled at major GCs, and the post-boot plateau (the warm-boot peak)
    # otherwise gets no major GC before /compile drops the live set. An idle
    # window lets the RTS idle GC (-I0.3 default, threaded RTS) run a major
    # collection at the plateau so the peak is actually recorded.
    log "serving after ${BOOT}s; settling 8s before /compile"
    sleep 8
    RESP=$(curl -sS --max-time 300 -X POST -H "Content-Type: text/plain" \
      --data-binary "$PROGRAM" "http://127.0.0.1:$PORT/compile" || true)
    if printf '%s' "$RESP" | grep -q '"js":'; then
      COMPILE_OK=true
      log "/compile ok"
    else
      log "/compile FAILED: $(printf '%s' "$RESP" | head -c 200)"
    fi
    sleep 1
    shutdown
    OUTCOME="ok"
    break
  fi
  if [ $(( $(date +%s) - START )) -gt "$TIMEOUT_S" ]; then
    log "timeout after ${TIMEOUT_S}s; SIGINT"
    shutdown
    OUTCOME="timeout"
    break
  fi
  sleep 2
done

python3 "$HERE/append_result.py" \
  --scenario "$SCEN" --mode "$MODE" --maxheap "$MAXH" \
  --outcome "$OUTCOME" --boot-seconds "$BOOT" --compile-ok "$COMPILE_OK" \
  --sfile "$SFILE" --outfile "$OUTFILE" --errfile "$ERRFILE" \
  --results "$HERE/results.json"
