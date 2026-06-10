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
import time
import urllib.request
import urllib.error
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8787"))
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", "30"))        # requests
RATE_WINDOW = int(os.environ.get("RATE_WINDOW", "3600"))    # per seconds, per IP
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-haiku-4-5-20251001")
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
well-known national one — if it is not written below, do not give it.
- You are not a clinician. Do not give medical, clinical, diagnostic, or legal advice. \
Do not recommend medications or treatment decisions; instead direct people to the \
appropriate program for an assessment.
- Do not ask for or store personal health information (name, date of birth, diagnoses, \
insurance numbers). If someone shares it, do not repeat it back; gently point them to \
the secure online referral form or a phone number instead.
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
- Politely decline questions unrelated to Coastal Horizons.

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
        # behind Render/most proxies the real IP is in X-Forwarded-For
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() if fwd else self.client_address[0]

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
            reply = call_claude(clean)
            self._send(200, {"reply": reply, "mode": "live"})
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            self._send(502, {"error": f"Claude API error {e.code}", "detail": detail})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")


if __name__ == "__main__":
    mode = "LIVE (Claude API)" if API_KEY else "MOCK (set ANTHROPIC_API_KEY for live answers)"
    print(f"Coastal Horizons assistant — http://localhost:{PORT}  [{mode}]")
    print(f"Knowledge base: {len(load_knowledge_base()):,} chars from kb/*.md")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
