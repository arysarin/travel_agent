# Deploying

Two options, depending on whether you want to deal with GCP billing:

- **Streamlit Community Cloud** (below) — free, no credit card, deploys
  straight from this GitHub repo. Simplest path if you just want a demo
  link.
- **Cloud Run** (further down) — needs a GCP project with billing enabled
  (free tier covers a portfolio demo, but billing still has to be turned
  on), more control (custom timeout, session affinity, Secret Manager),
  and no sleep-after-inactivity.

## Option A: Streamlit Community Cloud (no billing required)

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in
   with GitHub (the same account this repo is pushed to).
2. Click "New app", pick this repo, branch `main`, main file path
   `streamlit_app.py`. It auto-detects `requirements.txt`.
3. Before (or after) deploying, open **Advanced settings → Secrets** and
   paste your key/value pairs in TOML format. Run this locally yourself
   so your actual key values never have to be pasted into chat with me:
   ```bash
   python deploy/env_to_secrets_toml.py
   ```
   Copy its output into the Secrets box.
4. Deploy. Flat (non-sectioned) TOML secrets are automatically exposed as
   OS environment variables too, which is exactly what
   `travel_adviser/config.py` already reads via `os.environ.get(...)` —
   no code changes needed for this path.

Free tier limits: 1 GB RAM, the app sleeps after 12 hours of no visits
(wakes back up on the next visit, just a ~30s cold start), one private
app allowed (public apps are unlimited).

## Option B: Cloud Run (requires GCP billing)

### 1. One-time setup (you do this — I can't create a GCP account/billing for you)

1. Create a project at [console.cloud.google.com](https://console.cloud.google.com)
   (or reuse an existing one) and **enable billing** on it. Cloud Run's free
   tier is generous (2M requests/month, 360k GB-seconds), so a portfolio demo
   should cost close to $0, but billing still has to be turned on.
2. Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install)
   for Windows.
3. Authenticate and set the project:
   ```bash
   gcloud auth login
   gcloud config set project <YOUR_PROJECT_ID>
   ```

You don't need Docker installed locally — `deploy/deploy.sh` uses
`gcloud run deploy --source`, which builds the container remotely via Cloud
Build.

### 2. Deploy

From the repo root, with your `.env` already filled in:

```bash
./deploy/deploy.sh <YOUR_PROJECT_ID>
```

This enables the required APIs (Cloud Run, Cloud Build, Artifact Registry,
Secret Manager), stores your API keys in Secret Manager (not as plain env
vars — they'd otherwise show up in `gcloud run services describe` output
and deploy logs), and deploys the service. Takes a few minutes on first
run; re-running after a code change redeploys and updates any secrets
that changed in `.env`.

**The deployed service is public** (`--allow-unauthenticated`) — anyone
with the URL can use it, which burns your API quota/keys. That's the
point for a portfolio demo link, but if you'd rather it be private, edit
`deploy/deploy.sh` and swap that flag for `--no-allow-unauthenticated`;
you'll then need `gcloud auth print-identity-token` to reach it yourself.

### 3. What's different from local dev

- Runs on `requirements-deploy.txt` (no `google-adk[eval]`/pytest — those
  are dev-only) instead of `requirements.txt`.
- JSONL invocation logs go to `/tmp` inside the container — Cloud Run's
  filesystem isn't persistent across instance restarts, so this is
  best-effort debugging output, not a durable log. For real log
  retention, the ADK invocation events are also visible in Cloud
  Logging automatically (stdout/stderr Cloud Run captures).
- `--timeout 900` (15 min) and `--session-affinity` are set because a
  full trip-planning run can take several minutes and needs to stay on
  the same instance for its WebSocket connection.
- `--min-instances 0`: scales to zero when idle (no cost while unused),
  at the cost of a cold start (~10-20s) on the first request after a
  quiet period.

### 4. Redeploying after code changes

Just re-run the same command:

```bash
./deploy/deploy.sh <YOUR_PROJECT_ID>
```

### 5. Tearing it down

```bash
gcloud run services delete travel-adviser --project <YOUR_PROJECT_ID> --region us-central1
```

Secrets in Secret Manager aren't deleted by this — remove them separately
with `gcloud secrets delete <name>` if you want them gone too.
