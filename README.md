# Travel Adviser

A multi-agent trip planner built on [Google ADK](https://google.github.io/adk-docs/).
A coordinator agent delegates to six specialized sub-agents, aggregates
their outputs, enforces the stated budget by revising the plan (not just
reporting the overage), and returns one merged recommendation.

## Architecture

```
Travel Adviser (Coordinator — SequentialAgent pipeline)
     │
     ├──> Destination Recommendation Agent        (pure LLM)
     ├──> planning_loop_agent  (capped at MAX_BUDGET_ROUNDS rounds)
     │        ├──> Itinerary Planning Agent        (pure LLM)
     │        ├──> Transportation Agent  ───> SerpAPI Google Flights, Amadeus backup
     │        ├──> Accommodation Agent   ───> SerpAPI Google Hotels
     │        └──> Budget Optimization Agent       (deterministic cost math + LLM cut suggestions)
     ├──> Weather & Risk Assessment Agent ───> OpenWeatherMap
     └──> Final Merge Agent                       (combines everything into one response)
```

`planning_loop_agent` runs itinerary/flight/hotel generation together with
the budget check. If the budget agent finds the plan over budget, it states
specific cuts; the itinerary/transportation/accommodation agents revise
their own prior output on the next loop iteration. The loop exits as soon
as the plan is within budget, or after `MAX_BUDGET_ROUNDS` iterations
(default 3) — whichever comes first — so a stubborn overage can't run up
unbounded LLM cost.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then fill in `.env` with your own keys:

- `GOOGLE_API_KEY` — [Google AI Studio](https://aistudio.google.com) (Gemini)
- `SERPAPI_API_KEY` — [SerpAPI](https://serpapi.com) (Google Flights + Google Hotels engines)
- `OPENWEATHER_API_KEY` — [OpenWeatherMap](https://openweathermap.org/api)
- `GROQ_API_KEY` (optional) — [Groq Console](https://console.groq.com/keys)
- `OPENROUTER_API_KEY` (optional) — [OpenRouter](https://openrouter.ai/keys)
- `AMADEUS_API_KEY` / `AMADEUS_API_SECRET` (optional, both together) — [Amadeus for Developers](https://developers.amadeus.com)

Every tool function degrades gracefully with a structured `{"error": ...}`
response (rather than crashing) if a key is missing or the call times out,
so the app still runs — with reduced fidelity — before you've added real
keys.

### Model fallback chain

Free-tier LLM limits are tight for a system that makes this many calls per
request — Gemini's `gemini-3.6-flash` caps out at 20 requests/day, easy to
exceed in 2-3 trip-planning runs. Every agent (see
`travel_adviser/model_provider.py`) tries, in order, however many of these
are configured, moving to the next one whenever the current one returns a
429 (quota exhausted) or 503 (overloaded):

1. `TRAVEL_ADVISER_MODEL` (primary Gemini model, always tried first)
2. `GEMINI_FALLBACK_MODEL` — a *second* Gemini model under the same key.
   Free-tier quota is tracked per model name, so this is a separate
   20/day bucket at no extra signup cost — the cheapest resilience add.
   Set to blank to disable.
3. `GROQ_MODEL` via Groq, if `GROQ_API_KEY` is set
4. `OPENROUTER_MODEL` via OpenRouter's free (`:free`-suffixed) models, if
   `OPENROUTER_API_KEY` is set — genuinely free, no card, but the free
   lineup rotates; check
   [openrouter.ai/models?max_price=0](https://openrouter.ai/models?max_price=0)
   if it 404s. (Cerebras was considered here too, but as of August 2026
   its no-card free tier ended — it now requires a payment method for a
   $5/30-day trial, so it's not wired in by default.)

Any rung left blank is simply skipped; leave everything but the primary
model blank to run on Gemini alone, unchanged from a single-provider setup.
Groq's own model lineup also changes over time — if `GROQ_MODEL` ever
404s, run
`curl -H "Authorization: Bearer $GROQ_API_KEY" https://api.groq.com/openai/v1/models`
to see what's currently live on your key.

The chain only cleanly recovers when a rung fails *before* it has streamed
any output for that turn (the normal case for a quota error). If a rung
fails mid-stream, you may see a truncated response from it followed by the
full response from the next rung — a known limitation of
`travel_adviser/fallback_llm.py`, not worth the complexity to fix for this
project's scope.

**Cross-agent mixed-provider history.** Each of the 6 agents builds its
own independent fallback chain (`get_model()` is called separately per
agent) and always starts back at rung 1. So if `itinerary_agent` falls
through to Groq mid-pipeline, and then `transportation_agent` starts its
own turn back at Gemini, Gemini receives conversation history containing
Groq-authored function calls — which don't carry Gemini's proprietary
`thought_signature`, and Gemini's API rejects replaying those outright
("Function call is missing a thought_signature"). In practice this mostly
surfaces when Gemini's quota is exhausted *inconsistently* mid-run rather
than cleanly for the whole request; it's a known architectural limitation,
not something worth solving for this project's scope.

### Amadeus flight-search backup

SerpAPI's free tier is only 100 searches/month. If `AMADEUS_API_KEY` and
`AMADEUS_API_SECRET` are both set, `search_flights`
(`travel_adviser/tools/flights.py`) falls back to Amadeus's test
environment whenever SerpAPI is unavailable. Amadeus requires exact
3-letter IATA airport codes (SerpAPI tolerates looser input like city
names) — `transportation_agent`'s instructions already tell it to always
use IATA codes for this reason.

## Running

```bash
adk web
```

Opens ADK's dev UI at the printed localhost URL. Pick the `travel_adviser`
app and try a request like:

> Plan a 5-day trip to Japan under $2500.

Use the trace view to see which sub-agents fired, in what order, and how
many rounds the budget loop ran.

VS Code users: `.vscode/launch.json` has debug configs for `adk web`,
`adk run travel_adviser`, `streamlit run`, and the currently open test file.

## Frontend (Streamlit)

`streamlit_app.py` is a simple demo UI: a text box for the trip request, a
submit button, and the merged final plan rendered below (with each
individual agent's raw output available in an expander for debugging).

```bash
streamlit run streamlit_app.py
```

It runs the agent in-process via ADK's `InMemoryRunner` — no separate
`adk api_server` needed, one process, one command. It runs the *whole*
pipeline per submission (not a back-and-forth chat), waits for it to
finish, then renders everything at once — there's no live token
streaming. A failed run (provider quota/rate limit, the most common cause)
shows the actual error inline rather than crashing the page.

Each full run touches every one of the 7 agents at least once, which adds
up fast against free-tier limits — Gemini's 20 requests/day is easy to
exhaust in 2-3 submissions, and if it's already exhausted, *every* call in
that run falls through to Groq at once, which can blow past Groq's
8,000 tokens/minute cap within a single run. That's expected, not a bug;
it just means a full green run needs either Gemini quota still available
that day, or a quiet minute for Groq's per-minute budget to recover.

## Tests

```bash
pytest
```

`tests/test_tools_budget.py` is pure arithmetic and needs no API keys.
`tests/test_tools_flights.py`, `test_tools_hotels.py`, and
`test_tools_weather.py` verify the graceful-fallback path when a key is
missing — they don't require live keys either.

## Eval set (regression checks)

`tests/evals/travel_adviser.evalset.json` has 8 varied trip requests —
destination given vs. "surprise me", one-way vs. round-trip, tight and
impossible budgets, and far-future dates that fall outside OpenWeatherMap's
5-day free-tier forecast. Each case only asserts the coordinator's
top-level routing (which sub-agents it transferred to, and in what order),
via `tool_trajectory_avg_score` with `IN_ORDER` matching (configured in
`tests/evals/test_config.json`) — that tolerates the many extra tool calls
a real run makes and only fails if a key transfer is missing or
out of order.

Install the eval extra once (adds pandas/tabulate etc. on top of the base
deps):

```bash
pip install -e ".[eval]"
```

Run one case at a time — each case is a full live agent run and will
spend real LLM quota, so running all 8 back-to-back can exhaust the
Gemini free tier in one shot:

```bash
adk eval travel_adviser "tests/evals/travel_adviser.evalset.json:domestic_short_trip" --config_file_path tests/evals/test_config.json --print_detailed_results
```

Drop the `:case_id` suffix to run every case in the file. Each case also
has a `note` in `tests/evals/generate_evalset.py` describing what to
eyeball manually in the response (e.g. "does it clearly say it's still
over budget?") — the automated trajectory check can't see that, only
whether the right agents fired.

To add or edit a case, edit the `CASES` list in
`tests/evals/generate_evalset.py` and regenerate the JSON (don't hand-edit
it — it has to match ADK's pydantic eval schema exactly):

```bash
python tests/evals/generate_evalset.py
```

## Logging

Every tool call is appended as one JSON line to
`logs/travel_adviser.jsonl` (path configurable via
`TRAVEL_ADVISER_LOG_PATH`), recording the input, output, latency, and any
error — useful for debugging sub-agent routing and for evaluating the
system afterward.

## Scope of this build

This covers the spec's Phases 1-4 (environment, tools, sub-agents,
coordinator), Phase 6 (eval set), and part of Phase 7 (Streamlit
frontend) — a runnable, regression-checkable backend with a demo UI. Not
covered: the Flutter frontend alternative or deployment (Cloud Run /
Vertex Agent Engine) from the full spec.
