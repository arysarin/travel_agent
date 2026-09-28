# Cloud Run image for the Streamlit UI + agent, run in-process (no separate
# adk api_server — same model as local dev, see streamlit_app.py).

FROM python:3.12-slim

WORKDIR /app

# Install deps first so this layer caches across rebuilds that only change
# application code.
COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt

COPY streamlit_app.py .
COPY travel_adviser/ ./travel_adviser/

# Cloud Run injects $PORT (defaults to 8080) and expects the container to
# listen on it — shell form so $PORT actually expands. enableCORS=false and
# enableXsrfProtection=false are the standard pair for running Streamlit
# behind Cloud Run's own HTTPS-terminating proxy, which otherwise conflicts
# with Streamlit's same-origin checks.
CMD streamlit run streamlit_app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false
