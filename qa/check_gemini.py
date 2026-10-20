"""Checks what your Gemini API key can do: plain text, reading web pages (free mode), Google Search (paid).

Run:  .venv/bin/python qa/check_gemini.py [model]
Uses GEMINI_API_KEY from the environment / .env, or the key saved in the dashboard. Costs nothing on a free key.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402
from google import genai  # noqa: E402
from google.genai import errors, types  # noqa: E402

from scheduler import db  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
for env_file in (ROOT / ".env", ROOT / "scheduler" / ".env"):
    load_dotenv(env_file)

model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash"
db.init()
key = db.get_secret("gemini_api_key")
if not key:
    sys.exit("No Gemini API key found. Add it in the dashboard (Connections) or set GEMINI_API_KEY.")

client = genai.Client(api_key=key, http_options=types.HttpOptions(
    timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)))
checks = [
    ("Writing text", "Reply with just: OK", None, "needed for every briefing"),
    ("Reading web pages", "In 5 words, what is this site? https://www.rbi.org.in/",
     [types.Tool(url_context=types.UrlContext())], "used by Free mode"),
    ("Google Search", "Reply with just: OK", [types.Tool(google_search=types.GoogleSearch())],
     "used by Google Search mode (needs billing)"),
]
results = {}
print(f"Model: {model}\n")
for name, prompt, tools, why in checks:
    try:
        client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(tools=tools))
        results[name] = True
        print(f"✅ {name:18} works      ({why})")
    except errors.APIError as exc:
        results[name] = False
        reason = "limit/billing (429)" if exc.code == 429 else f"error {exc.code}: {(exc.message or '')[:80]}"
        print(f"❌ {name:18} {reason}  ({why})")

print()
if results["Writing text"] and results["Reading web pages"]:
    print("➡️  Free mode works with this key." + (" Google Search mode works too." if results["Google Search"] else
          " Google Search mode needs billing turned on for this key's project."))
elif not results["Writing text"]:
    print("➡️  The key can't make any requests: check the key, or the free limit is used up for today.")
else:
    print("➡️  Reading web pages failed: Free mode will only see headlines and summaries.")
