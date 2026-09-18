"""Environment-driven configuration, loaded once at import time."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")

MODEL_NAME = os.environ.get("TRAVEL_ADVISER_MODEL", "gemini-3.6-flash")

# Every agent's model is a fallback chain (see model_provider.py) built from
# whichever of these are configured, tried in this order. Each is optional
# and independent — leave any of them blank to skip that rung.

# A second Gemini model under the SAME Google API key. Free-tier quota is
# tracked per model name, so this is a separate 20/day bucket at no extra
# signup cost — the cheapest possible resilience add. Blank to disable.
GEMINI_FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# OpenRouter's free (":free"-suffixed) models — genuinely free, no card,
# but the free lineup rotates over time; if OPENROUTER_MODEL ever 404s,
# check https://openrouter.ai/models?max_price=0 for the current list.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731:free")

# Amadeus is a self-serve backup to SerpAPI for flight search specifically
# (SerpAPI's free tier is only 100 searches/month). Both keys are required
# together or not at all — get them from https://developers.amadeus.com.
AMADEUS_API_KEY = os.environ.get("AMADEUS_API_KEY", "")
AMADEUS_API_SECRET = os.environ.get("AMADEUS_API_SECRET", "")

MAX_LLM_CALLS = int(os.environ.get("MAX_LLM_CALLS", "20"))
MAX_BUDGET_ROUNDS = int(os.environ.get("MAX_BUDGET_ROUNDS", "3"))
API_TIMEOUT_SECONDS = float(os.environ.get("API_TIMEOUT_SECONDS", "10"))

LOG_PATH = Path(os.environ.get("TRAVEL_ADVISER_LOG_PATH", "logs/travel_adviser.jsonl"))
