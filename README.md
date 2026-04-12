# 🏛️ Mississippi SoS Regulation Assistant

A Retrieval-Augmented Generation (RAG) application that queries Mississippi Secretary of State regulations using Amazon Bedrock (AI models) and OpenSearch Serverless (vector database).

---

## Quick Start

1. Get the latest code
   ```bash
   git clone https://github.com/spicyneutrino/AI-Innovation-Phase-1.git
   cd AI-Innovation-Phase-1
   ```

2. Install dependencies
   This project uses uv to manage dependencies automatically from the lockfile.
   ```bash
   uv sync
   ```

   If `uv` is not available, you can:
   - Install `uv` (recommended):
     ```bash
     pip install --user uv
     # or
     pipx install uv
     ```
   - Or install dependencies directly:
     ```bash
     pip install -r requirements.txt
     ```
   - Or install and run Streamlit directly:
     ```bash
     pip install --user streamlit
     python -m streamlit run src/app.py
     ```

   Consider using a virtual environment (venv) or pipx to avoid polluting your global Python environment.

3. Set AWS credentials
   The app needs credentials to access your AWS account. Use the environment variables below (replace the placeholder values).
   ```bash
   export AWS_ACCESS_KEY_ID="YOUR_ACCESS_KEY"
   export AWS_SECRET_ACCESS_KEY="YOUR_SECRET_KEY"
   export AWS_SESSION_TOKEN="YOUR_SESSION_TOKEN"
   export AWS_DEFAULT_REGION="us-east-1"
   ```

4. Run the application
   Starts the local web server and opens the app in your browser:
   ```bash
   uv run streamlit run src/app.py
   ```

## SoS crawler and Playwright (distrobox)

The automated crawler is packaged as `sos_crawler` and uses Scrapy + Playwright (Chromium). On hosts where Playwright’s browser dependencies are isolated in a container, use your Playwright distrobox first, then install and run from the repository root:

```bash
distrobox enter playwright-distrobox
cd /path/to/AI-Innovation-Phase-1
uv sync
uv run playwright install chromium
uv run sos-crawler crawl --states AR --max-retries 0
```

By default, crawl outputs are written under `var/sos_crawler/` (logs/output/downloads/cache). You can override with `SOS_CRAWLER_RUNTIME_DIR=/path` or `--runtime-dir /path`.

### AWS Lambda note (read-only filesystem)

AWS Lambda is read-only except for `/tmp`. When `AWS_LAMBDA_FUNCTION_NAME` is set, the crawler will automatically use:

- `/tmp/sos_crawler` (unless you override with `SOS_CRAWLER_RUNTIME_DIR` or `--runtime-dir`)

## SoS crawler with Docker (Playwright included)

If you don’t want to use distrobox, you can run the crawler in Docker. This is **crawler-only** (no Streamlit app) and includes Chromium + Playwright dependencies via the official Playwright base image.

### Build

```bash
docker build -t sos-crawler .
```

### Run (single state)

Mount the runtime directory so outputs land on your host:

```bash
docker run --rm \
  -v "$PWD/var/sos_crawler:/app/var/sos_crawler" \
  -e SOS_CRAWLER_RUNTIME_DIR=/app/var/sos_crawler \
  sos-crawler uv run sos-crawler crawl --states TX --max-retries 0
```

### Run (multi-state parallel)

```bash
docker run --rm \
  -v "$PWD/var/sos_crawler:/app/var/sos_crawler" \
  -e SOS_CRAWLER_RUNTIME_DIR=/app/var/sos_crawler \
  sos-crawler uv run sos-crawler crawl --states MS AL AR TX --max-workers 4 --max-retries 0
```

### Docker Compose (optional)

```bash
docker compose build
docker compose run --rm crawler uv run sos-crawler crawl --states AL --max-retries 0
```

## Troubleshooting
- Ensure your AWS credentials and region are set correctly.
- If commands fail, confirm `uv` is installed and available in your PATH.


