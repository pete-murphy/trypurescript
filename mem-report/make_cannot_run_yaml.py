#!/usr/bin/env python3
"""Generate the trim-cannot-run scenario's spago.yaml.

Reads the *full* scenario's spago.yaml and deletes every entry of the
package.dependencies list that appears in cannot-run.json's `broken_closure`
array (the 148-package "cannot run in the playground" closure from the PR
investigation). Set subtraction only: the closure already contains all
transitive dependents, so the result is dependency-consistent.

Usage: python3 make_cannot_run_yaml.py
       (run from anywhere; paths are relative to this script)
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FULL_YAML = os.path.join(HERE, "scenarios", "full", "spago.yaml")
CANNOT_RUN = os.path.join(HERE, "cannot-run.json")
OUT_YAML = os.path.join(HERE, "scenarios", "trim-cannot-run", "spago.yaml")

closure = set(json.load(open(CANNOT_RUN))["broken_closure"])

out_lines = []
kept = removed = 0
in_deps = False
for line in open(FULL_YAML).read().splitlines(keepends=True):
    if re.match(r"^  dependencies:", line):
        in_deps = True
        out_lines.append(line)
        continue
    if in_deps:
        m = re.match(r"^    - (\S+)\s*$", line)
        if m:
            if m.group(1) in closure:
                removed += 1
                continue
            kept += 1
        elif line.strip() and not line.startswith("    "):
            in_deps = False
    out_lines.append(line)

os.makedirs(os.path.dirname(OUT_YAML), exist_ok=True)
with open(OUT_YAML, "w") as f:
    f.writelines(out_lines)

print(f"wrote {OUT_YAML}: kept {kept} deps, removed {removed} (closure size {len(closure)})")
