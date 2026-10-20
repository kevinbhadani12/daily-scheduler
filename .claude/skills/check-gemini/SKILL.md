---
name: check-gemini
description: Find out why Gemini fails or what the user's Gemini key allows (quota/limit reached, 429, "I have Gemini Pro", billing, free vs paid). Probes the key and explains the free and paid options in simple words.
---

# Check the Gemini key

1. Run the probe (it's free on a free key, and only makes 3 tiny requests):
   `.venv/bin/python qa/check_gemini.py` (add a model id to test another model, e.g. `gemini-4-argon`)

2. Read the result:
   | Result | Meaning | What to tell the user |
   |---|---|---|
   | Text ✅, Reading pages ✅, Google Search ❌ 429 | Normal free key | Use **Free mode** (the default). Google Search mode needs billing |
   | All ✅ | Billing is on | Both modes work. Search mode gives deeper briefings |
   | Text ❌ 429 | Free daily/minute limit used up | Wait (resets daily), use fewer briefings, or lower effort |
   | Text ❌ 400/403 "key" | Wrong or disabled key | Make a new key at aistudio.google.com/apikey and paste it in Connections |
   | Recent activity says "overloaded" / 503 | Google's servers are busy (common on the free tier) | Not the user's fault. The app already switches to the backup model and retries. If it happens every day, set an earlier time or a lower effort |

3. Also check the app's settings (`python app.py list`, or the dashboard): is `research_mode` "free"? In free mode,
   does any briefing or the default use a model in `db.PAID_ONLY_MODELS`?

4. **If the user says "I pay for Gemini Pro / Google AI Pro":** explain that the subscription covers the Gemini
   app and the AI Studio website, **not API keys**. API use is billed separately. AI Pro does include about
   **$10/month of Google Cloud credits** (Google Developer Program, needs billing enabled), which can pay for
   Search mode. Free mode needs none of this.

5. Never turn on paid features for the user, and never tell them billing is required for the default setup.
