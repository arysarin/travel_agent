#!/usr/bin/env bash
# Deploys Travel Adviser to Cloud Run.
#
# Prerequisites (do these once, outside this script — see DEPLOYMENT.md):
#   1. A GCP project with billing enabled.
#   2. gcloud CLI installed and authenticated: `gcloud auth login`
#   3. `gcloud config set project <PROJECT_ID>`
#
# Usage:
#   ./deploy/deploy.sh <PROJECT_ID> [REGION]
#
# Reads API keys from .env in the repo root (never committed) and stores
# them in Secret Manager rather than passing them as plain env vars, so
# they don't end up in Cloud Run's deploy-time logs or `gcloud run
# services describe` output.

set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh <PROJECT_ID> [REGION]}"
REGION="${2:-us-central1}"
SERVICE_NAME="travel-adviser"
ENV_FILE="$(dirname "$0")/../.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found. Copy .env.example to .env and fill in your keys first." >&2
  exit 1
fi

# Secrets: created/updated in Secret Manager, then mounted as env vars.
# Only ones with a real value get created — an unset optional key (e.g.
# AMADEUS_API_KEY if you're not using that fallback) is simply skipped,
# matching local behavior where a blank key means "that rung is disabled."
SECRET_VARS=(
  GOOGLE_API_KEY
  SERPAPI_API_KEY
  OPENWEATHER_API_KEY
  GROQ_API_KEY
  OPENROUTER_API_KEY
  AMADEUS_API_KEY
  AMADEUS_API_SECRET
)

get_env_value() {
  grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-
}

echo "==> Enabling required APIs on $PROJECT_ID..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  --project "$PROJECT_ID"

SECRET_ARGS=()
for var in "${SECRET_VARS[@]}"; do
  value="$(get_env_value "$var")"
  if [[ -z "$value" ]]; then
    echo "==> Skipping $var (blank in .env)"
    continue
  fi
  secret_name="travel-adviser-$(echo "$var" | tr '[:upper:]_' '[:lower:]-')"
  if gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "==> Updating secret $secret_name"
    printf '%s' "$value" | gcloud secrets versions add "$secret_name" --project "$PROJECT_ID" --data-file=-
  else
    echo "==> Creating secret $secret_name"
    printf '%s' "$value" | gcloud secrets create "$secret_name" --project "$PROJECT_ID" --data-file=-
  fi
  SECRET_ARGS+=("$var=$secret_name:latest")
done
SECRETS_FLAG=$(IFS=,; echo "${SECRET_ARGS[*]}")

# Non-secret config, safe as plain env vars. TRAVEL_ADVISER_LOG_PATH points
# at /tmp — Cloud Run's filesystem is writable but not persistent across
# instance restarts, so JSONL logs here are best-effort/debugging only,
# not a durable log store.
ENV_ARGS="TRAVEL_ADVISER_LOG_PATH=/tmp/travel_adviser.jsonl"
for var in TRAVEL_ADVISER_MODEL GEMINI_FALLBACK_MODEL GROQ_MODEL OPENROUTER_MODEL \
           MAX_LLM_CALLS MAX_BUDGET_ROUNDS API_TIMEOUT_SECONDS; do
  value="$(get_env_value "$var")"
  [[ -n "$value" ]] && ENV_ARGS="$ENV_ARGS,$var=$value"
done

echo "==> Deploying $SERVICE_NAME to $REGION..."
gcloud run deploy "$SERVICE_NAME" \
  --source "$(dirname "$0")/.." \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 900 \
  --min-instances 0 \
  --max-instances 3 \
  --session-affinity \
  --set-secrets "$SECRETS_FLAG" \
  --set-env-vars "$ENV_ARGS"

echo "==> Done. Service URL printed above — it's publicly reachable (--allow-unauthenticated)."
