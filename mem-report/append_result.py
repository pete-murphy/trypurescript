#!/usr/bin/env python3
"""Parse the RTS -S file's trailing summary for one measure.sh run and
append a JSON object to results.json (a JSON array).

maxLive = "bytes maximum residency"; the module count comes from the SPARKS
line of the summary (one spark per module compile) and, on cold runs, is
cross-checked against the "[ N of M ] Compiling" lines on stdout.
"""
import argparse
import json
import os
import re


def parse_summary(sfile):
    out = {}
    if not os.path.exists(sfile):
        return out
    text = open(sfile, errors="replace").read()

    def num(pattern):
        m = re.search(pattern, text)
        return int(m.group(1).replace(",", "")) if m else None

    out["max_live_bytes"] = num(r"([\d,]+) bytes maximum residency")
    out["mem_in_use_mib"] = num(r"([\d,]+) MiB total memory in use")
    if out["mem_in_use_mib"] is None:
        mb = num(r"([\d,]+) MB total memory in use")
        out["mem_in_use_mib"] = mb
    out["allocated_bytes"] = num(r"([\d,]+) bytes allocated in the heap")
    sparks = re.search(r"SPARKS:\s*([\d,]+)", text)
    out["sparks"] = int(sparks.group(1).replace(",", "")) if sparks else None

    def secs(label):
        m = re.search(label + r"\s+time\s+([\d.]+)s\s+\(\s*([\d.]+)s elapsed\)", text)
        return {"cpu_s": float(m.group(1)), "elapsed_s": float(m.group(2))} if m else None

    out["mut"] = secs("MUT")
    out["gc"] = secs("GC")
    out["total"] = secs("Total")
    return out


def parse_modules_compiled(*files):
    """Highest M from '[ N of M ] Compiling' output (cold runs only)."""
    best = None
    for path in files:
        if not path or not os.path.exists(path):
            continue
        with open(path, errors="replace") as f:
            for line in f:
                m = re.search(r"\[\s*\d+ of (\d+)\s*\] Compiling", line)
                if m:
                    best = int(m.group(1))
    return best


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--maxheap", required=True)
    p.add_argument("--outcome", required=True)
    p.add_argument("--boot-seconds", default="null")
    p.add_argument("--compile-ok", default="false")
    p.add_argument("--sfile", required=True)
    p.add_argument("--outfile", required=True)
    p.add_argument("--errfile", default=None)
    p.add_argument("--results", required=True)
    a = p.parse_args()

    rec = {
        "scenario": a.scenario,
        "mode": a.mode,
        "maxheap": a.maxheap,
        "outcome": a.outcome,
        "boot_seconds": None if a.boot_seconds == "null" else int(a.boot_seconds),
        "compile_ok": a.compile_ok == "true",
    }
    rec.update(parse_summary(a.sfile))
    rec["modules_compiled"] = parse_modules_compiled(a.outfile, a.errfile)
    if rec.get("max_live_bytes"):
        rec["max_live_mb"] = round(rec["max_live_bytes"] / (1024 * 1024))

    results = []
    if os.path.exists(a.results):
        results = json.load(open(a.results))
    results.append(rec)
    with open(a.results, "w") as f:
        json.dump(results, f, indent=2)
        f.write("\n")
    print("[append_result] " + json.dumps(rec))


if __name__ == "__main__":
    main()
