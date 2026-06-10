# Coastal Horizons Website Assistant — MVP

An AI chat widget that helps coastalhorizons.org visitors find what services are offered in their county, how to make a referral, and where offices are located. Built in-house as an alternative to purchasing a chatbot product.

## Quick start

```bash
cd coastal-assistant
export ANTHROPIC_API_KEY=sk-ant-...   # get one at console.anthropic.com
python3 server.py
# open http://localhost:8787
```

No installs required — Python 3.9+ standard library only. Without an API key it runs in mock mode (UI works, canned replies).

## How it works

```
Visitor → chat widget (index.html) → server.py → Claude API (Haiku)
                                        ↑
                          kb/*.md  (curated site content)
```

The knowledge base (`kb/`) is hand-curated markdown taken from coastalhorizons.org: services, county-by-county coverage, the full locations/phone directory, and every referral pathway. The whole KB (~16 KB) is sent as the system prompt with prompt caching — at this size that's simpler and more accurate than a vector database. The model is instructed to answer *only* from this content and never invent phone numbers or programs.

`index.html` is a demo page that simulates the website; the widget itself (launcher button + chat panel) is self-contained and can be pasted into the real WordPress site as a snippet later, pointing at a hosted copy of `server.py`.

## Why build vs. buy

| | Build (this) | Buy (typical chatbot SaaS) |
|---|---|---|
| Cost | ~$5–20/mo hosting + API usage (see below) | ~$100–500+/mo |
| Content control | Full — we curate every fact | Vendor crawler, less control |
| Safety/crisis behavior | Custom (988, rape crisis line, no PHI) | Often generic |
| Maintenance | Update markdown files when site changes | Vendor dashboard |

**API cost estimate (Claude Haiku 4.5 with prompt caching):** roughly $0.002–0.005 per conversation. Even 3,000 conversations/month ≈ **$10–15/month**. Costs are capped further by the 700-token reply limit and 20-turn history cap.

## HIPAA / privacy guardrails (important for a behavioral health org)

- The assistant is **informational only** — it's instructed to never give clinical advice and to redirect treatment questions to an assessment.
- It is instructed **not to collect PHI** and not to repeat back any personal details a visitor shares; it points people to the secure referral form or a phone number instead.
- Crisis safety: any indication of self-harm, harm to others, or sexual assault triggers an immediate handoff to 988, the Rape Crisis Line (910-392-7460), Open House (800-672-2903), or 911. These numbers are also pinned permanently in the widget UI.
- **No conversation data is stored** by this server (nothing is logged to disk). Note: messages are processed by Anthropic's API. Before production, decide whether chat content could constitute PHI; if so, options are (a) keep the bot strictly informational with a visible "don't share personal info" notice (current design), or (b) execute a BAA with the API provider. This needs a sign-off from compliance — flag for Ryan/Jim.
- The standard Anthropic API does not train on customer data by default.

## Production path

1. **Demo** (now): run locally, show Ryan/Jim.
2. **Pilot**: deploy `server.py` to a small host (Render/Railway/Fly.io free–$7 tier, or existing org infrastructure); add the widget snippet to WordPress; restrict CORS to coastalhorizons.org.
3. **Hardening**: rate limiting, basic analytics (count of questions by topic — no content), automated KB refresh from the site, Spanish-language chip, accessibility pass (WCAG 2.1 AA).

## Keeping content fresh

All facts live in `kb/*.md` — edit those files and restart. Sources:
- `services.md` — services overview pages
- `counties.md` — program service areas map
- `locations.md` — services directory
- `referrals.md` — referral forms and intake pathways
- `about-and-contact.md` — org info, crisis lines, fees

Content snapshot date: **June 10, 2026**.

## Files

- `server.py` — HTTP server + Claude API call (stdlib only)
- `index.html` — demo page + embeddable chat widget
- `kb/` — curated knowledge base

---
*Internal MVP prototype, not affiliated production software. Verify all phone numbers and program details against coastalhorizons.org before launch.*
