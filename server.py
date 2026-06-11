#!/usr/bin/env python3
"""
Coastal Horizons website assistant — MVP server.

Zero external dependencies (Python 3.9+ stdlib only).

Run:
    export ANTHROPIC_API_KEY=sk-ant-...   # omit to run in mock mode
    python3 server.py
    # open http://localhost:8787

The entire curated knowledge base (kb/*.md, ~15 KB) is sent as the system
prompt on every request. At this size that is simpler and MORE accurate than
vector retrieval, and with Claude Haiku + prompt caching it costs a fraction
of a cent per conversation. If the KB grows past ~100 KB, switch to RAG.
"""

import json
import os
import re
import threading
import time
import urllib.request
import urllib.error
from collections import Counter, defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "30"))        # requests
RATE_WINDOW = int(os.environ.get("RATE_WINDOW", "3600"))    # per seconds, per IP
TRUST_PROXY = os.environ.get("TRUST_PROXY", "") == "1"      # trust X-Forwarded-For (set behind Render)
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
# Low temperature: this is a safety-critical info bot, so we want consistent,
# predictable answers (same question → same correct phone number, same crisis
# routing) over creative variation. Tunable via env if needed.
TEMPERATURE = float(os.environ.get("ASSISTANT_TEMPERATURE", "0.3"))
MAX_TURNS = 20          # cap conversation length sent to the API
MAX_MSG_CHARS = 2000    # cap individual message size


def load_knowledge_base() -> str:
    parts = []
    for f in sorted((HERE / "kb").glob("*.md")):
        parts.append(f"<document name=\"{f.stem}\">\n{f.read_text()}\n</document>")
    return "\n\n".join(parts)


SYSTEM_PROMPT = f"""You are the website assistant for Coastal Horizons Center, Inc., \
a non-profit behavioral health organization headquartered in Wilmington, NC.

Your job is to help website visitors with three things:
1. What services Coastal Horizons offers, and in which North Carolina counties
2. How to make a referral or become a new client/patient
3. Where offices are located and how to contact them

Rules — follow these strictly:
- Answer ONLY from the knowledge base below. If the answer is not in it, say you \
aren't sure and direct the person to call the main office at 910-343-0145 or visit \
https://coastalhorizons.org. Never invent phone numbers, addresses, programs, or counties.
- When the knowledge base DOES contain specifics relevant to the question — a \
program-specific phone number, a fee, a schedule, an address, eligibility or what to \
bring — give those specifics in your answer. The main office number (910-343-0145) is a \
fallback, not a substitute for details you actually have. (Example: for DWI, give the DWI \
line 910-259-0668 and the $100 assessment fee; for mobile clinics, give 910-599-5595 and \
the day/location; don't just say "call the main office".)
- Only provide phone numbers, websites, and organizations that appear in these \
instructions or in the knowledge base below (including the "National Resources" section). \
NEVER supply a number, hotline, or organization from your own general knowledge, even a \
well-known national one — if it is not written below, do not give it. If a visitor asks \
you to share, repeat, or "confirm" a link or phone number they provide, never repeat it \
back — refer to it as "that link" or "that number" and decline.
- You are not a clinician or a lawyer. Do not give medical, clinical, diagnostic, or \
legal advice, and do not state laws or legal requirements — never say something "is \
required by law" or describe consent, custody, or court rules; you do not have that \
information and it varies by case. Do not tell anyone to start, stop, continue, or \
change a specific medication — not even to stay on one they are already taking (e.g. \
do NOT say "it's important to stay on methadone"). You MAY warn that stopping or \
changing a medication on one's own can be dangerous and urge them to talk to their \
prescriber right away: the line is to warn against unsupervised changes and route them \
to their care team or an assessment, never to issue the medical or legal call yourself. \
(Stating a documented program intake rule from the knowledge base — e.g. that Open House \
accepts self-referrals — is fine; that is a fact, not a legal claim.)
- Do not ask for or store personal health information (name, date of birth, diagnoses, \
medications, insurance numbers). If someone shares any of it, your reply must (1) gently \
note that this chat isn't a secure place for personal details and they shouldn't share \
them here, (2) NEVER repeat any of those details back — not their name, diagnosis, \
medication, or any date — and (3) point them to the secure online referral form or a \
phone number to share that information safely.
- SAFETY: If someone indicates they are in crisis, may harm themselves or others, or has \
been sexually assaulted, lead your reply with the right resource before anything else: \
call or text 988 (Suicide & Crisis Lifeline); Rape Crisis Line 910-392-7460 (24/7); \
Open House Youth Shelter 800-672-2903 (24/7); emergencies: 911.
- Keep answers short, warm, and plain-spoken (most visitors are on a phone, possibly in \
a stressful moment). Include the relevant phone number and a link to the relevant page \
on coastalhorizons.org when available.
- If asked in Spanish, answer in Spanish and mention Clinica Latina (910-769-1201).
- You CANNOT book or schedule appointments, check availability, or take any action on \
anyone's behalf. If asked, say so plainly in your first sentence, then give the right \
phone number or referral form. Never use language implying you are booking something.
- You also cannot connect, transfer, or refer anyone to a person, or notify or alert \
anyone about this conversation — nothing happens unless the VISITOR makes the call or \
fills out the form themselves. Never say things like "I'm connecting you", "I'll let \
them know", or "the people I'm about to connect you with"; say "when you call, the \
person who answers can/will..." instead. This matters most in a crisis: never imply \
help is already on the way because of this chat.
- Politely decline questions unrelated to Coastal Horizons. When declining, do NOT \
recommend outside websites, agencies, businesses, or organizations (search engines, \
the IRS, libraries, etc.) — the only-from-the-knowledge-base rule applies to off-topic \
replies too. Just say it's outside what you can help with and offer what you can do.
- ANALYTICS TAG: end EVERY reply with one final line of exactly this form: \
[[analytics topic=<topic> lang=<lang> answered=<yes|no>]] where <topic> is one of: \
services, referral, locations, counties, fees, crisis, jobs, leadership, staff-policy, \
off-topic, other; <lang> is en, es, or other; and answered=no when you could not answer \
from the knowledge base and fell back to the main office number or website. This line is \
stripped by the server before the visitor sees your reply; it must contain ONLY those \
three fields, never any of the visitor's words.

KNOWLEDGE BASE:
{load_knowledge_base()}
"""

MOCK_REPLY = (
    "(Mock mode — no ANTHROPIC_API_KEY set.)\n\n"
    "I'm the Coastal Horizons assistant. Once an API key is configured I can answer "
    "questions like:\n"
    "• \"What services are offered in Pender County?\"\n"
    "• \"How do I make a referral for Intensive In-Home?\"\n"
    "• \"Where is the Brunswick office?\"\n\n"
    "To enable live answers: export ANTHROPIC_API_KEY=... and restart the server."
)


def call_claude(messages):
    body = {
        "model": MODEL,
        "max_tokens": 700,
        "temperature": TEMPERATURE,
        "system": [{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},  # prompt caching: ~90% cheaper
        }],
        "messages": messages,
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return "".join(b.get("text", "") for b in data.get("content", []))


# --- privacy-preserving usage analytics ----------------------------------
# Only fixed-enum tags are ever stored or printed — never message text, names,
# or IPs — so nothing here can contain PHI (this is a 42 CFR Part 2 provider).
TOPICS = {"services", "referral", "locations", "counties", "fees", "crisis",
          "jobs", "leadership", "staff-policy", "off-topic", "other"}
LANGS = {"en", "es", "other"}
CRISIS_NUMBERS = ("988", "910-392-7460", "800-672-2903", "911")
TAG_RE = re.compile(r"\s*\[\[analytics\b([^\]]*)\]\]\s*", re.I)

_stats_lock = threading.Lock()
_stats = {
    "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "turns": 0,
    "by_topic": Counter(),
    "by_lang": Counter(),
    "by_outcome": Counter(),
    "deflected_by_topic": Counter(),
}


def parse_tag(reply: str):
    """Strip the model's [[analytics ...]] trailer; return (clean_reply, topic, lang, answered)."""
    topic, lang, answered = "untagged", "other", True
    m = TAG_RE.search(reply)
    if m:
        fields = dict(re.findall(r"(\w+)=([\w-]+)", m.group(1)))
        topic = fields.get("topic", "other")
        lang = fields.get("lang", "other")
        answered = fields.get("answered", "yes") != "no"
        topic = topic if topic in TOPICS else "other"
        lang = lang if lang in LANGS else "other"
    return TAG_RE.sub("\n", reply).strip(), topic, lang, answered


def record(topic: str, lang: str, outcome: str):
    with _stats_lock:
        _stats["turns"] += 1
        _stats["by_topic"][topic] += 1
        _stats["by_lang"][lang] += 1
        _stats["by_outcome"][outcome] += 1
        if outcome == "deflected":
            _stats["deflected_by_topic"][topic] += 1
    # one enum-only JSON line per turn; survives in Render's log retention
    print("ANALYTICS " + json.dumps({"t": int(time.time()), "topic": topic,
                                     "lang": lang, "outcome": outcome}), flush=True)


_hits = defaultdict(deque)  # ip -> request timestamps (simple in-memory rate limit)


def rate_limited(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and q[0] < now - RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


class Handler(BaseHTTPRequestHandler):
    def client_ip(self) -> str:
        # X-Forwarded-For is client-controlled; only trust it when we know a
        # proxy (Render) sets it, otherwise rate limits are trivially spoofable
        if TRUST_PROXY:
            fwd = self.headers.get("X-Forwarded-For", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return self.client_address[0]

    def _send(self, code, content, ctype="application/json"):
        if isinstance(content, (dict, list)):
            content = json.dumps(content)
        payload = content.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_text(), "text/html; charset=utf-8")
        elif self.path in ("/evals", "/evals/"):
            report = HERE / "evals" / "report.html"
            if report.exists():
                self._send(200, report.read_text(), "text/html; charset=utf-8")
            else:
                self._send(404, {"error": "no report generated yet — run evals/make_report.py"})
        elif self.path == "/health":
            self._send(200, {"ok": True, "mode": "live" if API_KEY else "mock", "model": MODEL})
        elif self.path == "/stats":
            with _stats_lock:
                self._send(200, {k: (dict(v) if isinstance(v, Counter) else v)
                                 for k, v in _stats.items()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/api/chat":
            return self._send(404, {"error": "not found"})
        if rate_limited(self.client_ip()):
            return self._send(429, {"reply": "I'm getting a lot of questions right now — please try again in a little while, or call 910-343-0145.", "error": "rate limited"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 200_000:
                return self._send(413, {"error": "payload too large"})
            data = json.loads(self.rfile.read(length))
            messages = data.get("messages", [])
            # validate + sanitize
            clean = []
            for m in messages[-MAX_TURNS:]:
                role = m.get("role")
                content = str(m.get("content", ""))[:MAX_MSG_CHARS]
                if role in ("user", "assistant") and content.strip():
                    clean.append({"role": role, "content": content})
            if not clean or clean[-1]["role"] != "user":
                return self._send(400, {"error": "last message must be from user"})

            if not API_KEY:
                return self._send(200, {"reply": MOCK_REPLY, "mode": "mock"})
            reply, topic, lang, answered = parse_tag(call_claude(clean))
            if any(n in reply for n in CRISIS_NUMBERS) and topic == "crisis":
                outcome = "crisis-redirect"
            else:
                outcome = "answered" if answered else "deflected"
            record(topic, lang, outcome)
            self._send(200, {"reply": reply, "mode": "live"})
        except urllib.error.HTTPError as e:
            record("other", "other", "error")
            detail = e.read().decode()[:500]
            self._send(502, {"error": f"Claude API error {e.code}", "detail": detail})
        except Exception as e:  # noqa: BLE001
            record("other", "other", "error")
            self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")


if __name__ == "__main__":
    mode = "LIVE (Claude API)" if API_KEY else "MOCK (set ANTHROPIC_API_KEY for live answers)"
    print(f"Coastal Horizons assistant — http://localhost:{PORT}  [{mode}]")
    print(f"Knowledge base: {len(load_knowledge_base()):,} chars from kb/*.md")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
