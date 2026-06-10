#!/usr/bin/env python3
"""Detect KB drift: re-fetch each kb/*.md file's source page(s) and verify the
phone numbers we publish still appear there. Stdlib only.

Usage:  python3 check_kb_freshness.py
Exit code = number of KB files with drifted (missing) phone numbers.
Unreachable pages are warnings, not failures (sites have outages).
"""

import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

KB = Path(__file__).parent / "kb"
URL_RE = re.compile(r"https?://(?:www\.)?(?:coastalhorizons\.org|samhsa\.gov|ncpgambling\.org)[^\s)>\"]*")
PHONE_RE = re.compile(r"\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}|\b1-8\d{2}-\d{3}-\d{4}\b")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        # phone numbers often live in tel: links
        for k, v in attrs:
            if k == "href" and v and v.startswith("tel:"):
                self.parts.append(v)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (KB freshness check)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    p = TextExtractor()
    p.feed(body)
    return " ".join(p.parts)


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def main():
    drifted, warnings = [], []
    all_fetched_digits = []          # text of every page fetched, for a global second pass
    candidates = []                  # (file, phone) pairs missing from their own file's pages
    for f in sorted(KB.glob("*.md")):
        text = f.read_text()
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        # page URLs only — flyers/PDFs and social links aren't text-checkable
        urls = [u for u in urls if not re.search(r"\.(pdf|jpg|png)$", u)]
        phones = list(dict.fromkeys(PHONE_RE.findall(text)))
        if not phones:
            continue
        if not urls:
            warnings.append(f"{f.name}: {len(phones)} phone number(s) but no source URL to check against")
            continue
        fetched, fetch_errors = "", []
        for u in urls:
            try:
                fetched += fetch_text(u)
            except Exception as e:  # noqa: BLE001
                fetch_errors.append(f"{u} ({e})")
        if not fetched:
            warnings.append(f"{f.name}: no source page reachable: {'; '.join(fetch_errors)}")
            continue
        fetched_digits = digits(fetched)
        all_fetched_digits.append(fetched_digits)
        missing = [ph for ph in phones
                   if digits(ph) not in fetched_digits and digits(ph).lstrip("1") not in fetched_digits]
        candidates.extend((f.name, ph) for ph in missing)
        status = "CHECK" if missing else "OK"
        print(f"[{status}] {f.name}: {len(phones)} number(s) vs {len(urls)} page(s)"
              + (f" — fetch errors: {'; '.join(fetch_errors)}" if fetch_errors else ""))

    # second pass: a number is only drift if it appears on NO fetched page —
    # KB files often cite numbers sourced from a sibling program's page
    global_digits = " ".join(all_fetched_digits)
    by_file = {}
    for fname, ph in candidates:
        d = digits(ph)
        if d not in global_digits and d.lstrip("1") not in global_digits:
            by_file.setdefault(fname, []).append(ph)
    drifted.extend(f"{fn}: number(s) on no fetched source page: {', '.join(phs)}"
                   for fn, phs in by_file.items())

    if warnings:
        print("\nWarnings (not failures):")
        for w in warnings:
            print(f"  ⚠ {w}")
    if drifted:
        print("\nDRIFT DETECTED — update the KB or confirm with the program:")
        for m in drifted:
            print(f"  ✘ {m}")
    else:
        print("\nAll checkable KB phone numbers still appear on their source pages.")
    sys.exit(len(drifted))


if __name__ == "__main__":
    main()
