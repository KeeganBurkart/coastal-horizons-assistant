#!/usr/bin/env python3
"""Generate a shareable HTML report from evals_results.json.

Usage:  python3 make_report.py
Output: evals/report.html  (served by server.py at /evals)
"""

import html
import json
import re
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
results = json.loads((HERE / "evals_results.json").read_text())

n = len(results)
passed = sum(1 for r in results if r["pass"])
cats = Counter(r["category"] for r in results)
cat_pass = Counter(r["category"] for r in results if r["pass"])

CAT_LABELS = {
    "crisis": "Crisis & safety",
    "substance-use": "Substance use help-seekers",
    "family": "Parents & caregivers",
    "spanish": "Spanish speakers",
    "justice": "Justice-involved",
    "dwi": "DWI services",
    "mobile-clinics": "Mobile clinics",
    "gambling": "Problem gambling",
    "veterans": "Veterans",
    "youth": "Youth shelter & housing",
    "professional": "Community partners & referrers",
    "locations": "Locations & logistics",
    "hallucination-trap": "Hallucination traps",
    "safety": "Clinical-advice red lines",
    "privacy": "Privacy (PHI handling)",
    "scope": "Off-topic handling",
    "injection": "Prompt injection & hijacking",
    "tone": "Tone with vulnerable visitors",
    "leadership": "Leadership & board",
    "careers": "Careers & jobs",
    "staff": "Staff (personnel policies)",
    "partners": "Partners & vendors (BAA/QSOA)",
    "redteam-minors": "Red team: minors at risk",
    "redteam-selfharm": "Red team: self-harm & violence",
    "redteam-medical": "Red team: medical & dosing",
    "redteam-promises": "Red team: invented promises",
    "redteam-manipulation": "Red team: manipulation & dependency",
}

missing = set(cats) - set(CAT_LABELS)
if missing:
    raise SystemExit(f"categories missing from CAT_LABELS (would be dropped from report): {missing}")


def render_reply(text: str) -> str:
    """Escape HTML, then apply the same minimal markdown the widget renders:
    ## headings and **bold** (replies are otherwise shown pre-wrap verbatim)."""
    esc = html.escape(text)
    esc = re.sub(r"^#{1,4}\s+(.+)$", r"<b>\1</b>", esc, flags=re.M)
    esc = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc)
    return esc

rows = []
for cat in CAT_LABELS:
    group = [r for r in results if r["category"] == cat]
    if not group:
        continue
    rows.append(f'<h2>{html.escape(CAT_LABELS[cat])} <span class="score">{cat_pass[cat]}/{cats[cat]}</span></h2>')
    for r in group:
        badge = '<span class="badge pass">PASS</span>' if r["pass"] else '<span class="badge fail">FAIL</span>'
        fail_html = ""
        if r["failures"]:
            items = "".join(f"<li>{html.escape(f)}</li>" for f in r["failures"])
            fail_html = f'<ul class="failures">{items}</ul>'
        turns = r.get("turns") or [r.get("query", "")]
        q = " ⟶ ".join(turns)
        if len(turns) > 1 and r.get("transcript"):
            body = "".join(
                f'<p class="t-{m["role"]}"><b>{"Visitor" if m["role"] == "user" else "Assistant"}:</b> {render_reply(m["content"])}</p>'
                for m in r["transcript"])
        else:
            body = render_reply(r.get("reply") or "") or "<i>(no reply — request error)</i>"
        judge_html = ""
        v = r.get("judge")
        if v and v.get("score") is not None:
            cls = "pass" if v.get("pass") else "fail"
            judge_html = (f'<p class="judge"><span class="badge {cls}">JUDGE {v["score"]}/5</span> '
                          f'{html.escape(v.get("reason", ""))}</p>')
        rows.append(f"""
<details {'class="failed"' if not r['pass'] else ''}>
  <summary>{badge} <b>{html.escape(r['persona'])}</b> — <span class="q">“{html.escape(q)}”</span></summary>
  <div class="reply">{body}</div>
  {judge_html}
  {fail_html}
</details>""")

page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Coastal Horizons Assistant — Quality Test Results</title>
<style>
 body{{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:#f6f4ef;color:#23323f;max-width:860px;margin:0 auto;padding:30px 18px}}
 h1{{font-size:24px}} h2{{font-size:17px;margin:26px 0 8px;color:#005a5e}}
 .sub{{color:#5b6b78;font-size:14px;margin:6px 0 4px}}
 .hero{{background:#fff;border:1px solid #e2e8ea;border-radius:14px;padding:20px 22px;margin:18px 0}}
 .big{{font-size:40px;font-weight:700;color:#00777b}}
 .score{{font-size:13px;color:#5b6b78;font-weight:400}}
 details{{background:#fff;border:1px solid #e2e8ea;border-radius:10px;padding:10px 14px;margin:7px 0}}
 details.failed{{border-color:#e3b3ae}}
 summary{{cursor:pointer;font-size:14px;line-height:1.5}}
 .q{{color:#41525f;font-style:italic}}
 .reply{{white-space:pre-wrap;font-size:13.5px;line-height:1.55;background:#f2f5f5;border-radius:8px;padding:12px;margin-top:10px}}
 .reply p{{margin:0 0 10px}} .t-user b{{color:#00777b}} .t-assistant b{{color:#41525f}}
 .badge{{display:inline-block;font-size:11px;font-weight:700;border-radius:5px;padding:2px 7px;margin-right:6px}}
 .badge.pass{{background:#d9efe3;color:#176b3f}} .badge.fail{{background:#f7dcd9;color:#9c2c20}}
 .failures{{color:#9c2c20;font-size:13px;margin:8px 0 2px 18px}}
 .judge{{font-size:12.5px;color:#41525f;margin-top:8px}}
 .note{{font-size:12.5px;color:#5b6b78;margin-top:30px;border-top:1px solid #e2e8ea;padding-top:14px}}
</style></head><body>
<h1>Coastal Horizons Assistant — Quality Test Results</h1>
<p class="sub">Automated test suite simulating real website visitors: people seeking treatment, parents, teens in crisis,
Spanish speakers, social workers, and adversarial cases designed to catch wrong or invented answers.</p>
<div class="hero">
  <div class="big">{passed}/{n} passed</div>
  <div class="sub">Every test checks the assistant's reply for required facts (correct phone numbers, programs, counties)
  and forbidden content (invented details, clinical advice, repeated personal information).
  Generated {time.strftime('%B %d, %Y')}.</div>
</div>
{''.join(rows)}
<p class="note">All test conversations are synthetic — written by the development team, not real visitors.
The assistant answers only from content curated from coastalhorizons.org. Crisis-related messages are always
redirected to 988, the Rape Crisis Line (910-392-7460), Open House (800-672-2903), or 911.</p>
</body></html>"""

out = HERE / "report.html"
out.write_text(page)
print(f"Wrote {out} — {passed}/{n} passed")
