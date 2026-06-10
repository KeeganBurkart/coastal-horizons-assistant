#!/usr/bin/env python3
"""
Eval runner for the Coastal Horizons assistant. Stdlib only.

Usage:
    python3 run_evals.py                          # against http://localhost:8787
    python3 run_evals.py --url https://coastal-horizons-assistant.onrender.com
    python3 run_evals.py --category crisis        # one category
    python3 run_evals.py --limit 10 --delay 1.5

Checks each reply for required facts (must_contain: every group must match,
a group matches if ANY alternative appears) and forbidden content
(must_not_contain). Writes results to evals_results.json. Exit code = #failures.

NOTE: the server rate-limits 30 requests/hour/IP by default. For full runs
against a deployed instance, set RATE_LIMIT=200 in its environment, or run
against a local server.
"""

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent


def ask(base_url: str, query: str) -> str:
    body = json.dumps({"messages": [{"role": "user", "content": query}]}).encode()
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    if "reply" not in data:
        raise RuntimeError(f"no reply: {data}")
    return data["reply"]


def check(case: dict, reply: str):
    # strip markdown emphasis so "does **not**" matches "does not"
    low = reply.replace("*", "").replace("_", "").lower()
    failures = []
    for group in case.get("must_contain", []):
        if not any(alt.lower() in low for alt in group):
            failures.append(f"missing any of: {group}")
    for bad in case.get("must_not_contain", []):
        if bad.lower() in low:
            failures.append(f"forbidden text present: {bad!r}")
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8787")
    ap.add_argument("--category", default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between requests")
    args = ap.parse_args()

    cases = json.loads((HERE / "evals.json").read_text())["cases"]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    results, n_fail = [], 0
    for i, case in enumerate(cases, 1):
        try:
            reply = ask(args.url, case["query"])
            failures = check(case, reply)
        except Exception as e:  # noqa: BLE001
            reply, failures = "", [f"request error: {e}"]
        ok = not failures
        n_fail += 0 if ok else 1
        status = "PASS" if ok else "FAIL"
        print(f"[{i:>2}/{len(cases)}] {status}  {case['id']:<12} {case['persona'][:48]}")
        for f in failures:
            print(f"         └─ {f}")
        results.append({**case, "reply": reply, "failures": failures, "pass": ok})
        time.sleep(args.delay)

    print(f"\n{len(cases) - n_fail}/{len(cases)} passed")
    out = HERE / "evals_results.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print(f"Full replies saved to {out}")
    sys.exit(n_fail)


if __name__ == "__main__":
    main()
