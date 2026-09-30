"""Converts .env to the TOML format Streamlit Community Cloud's Secrets box
expects, and prints it to your own terminal — run this locally yourself so
your key values never have to be pasted into chat.

Usage (from the repo root):
    python deploy/env_to_secrets_toml.py

Then copy the printed output into your app's Settings -> Secrets on
share.streamlit.io. Flat (non-sectioned) TOML entries like these are also
exposed as normal OS environment variables at runtime, which is what
travel_adviser/config.py already reads via os.environ.get(...) — no code
changes needed for this deployment target.
"""

from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
if not env_path.exists():
    raise SystemExit(f"{env_path} not found — copy .env.example to .env and fill it in first.")

print("# Paste this into share.streamlit.io -> your app -> Settings -> Secrets\n")
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    key, _, value = line.partition("=")
    print(f'{key.strip()} = "{value.strip()}"')
