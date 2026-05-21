# Setup

## Prerequisites

- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** (recommended) or pip
- **AWS account** with access to Amazon Bedrock Knowledge Bases and (for uploads) S3
- **Playwright Chromium** (crawler only): `uv run playwright install chromium`

## Clone and install

```bash
git clone https://github.com/spicyneutrino/AI-Innovation-Phase-1.git
cd AI-Innovation-Phase-1
uv sync
```

If `uv` is unavailable:

```bash
pip install -r requirements.txt
```

## Configuration

1. Copy the sample environment file:

   ```bash
   cp .env.example .env
   ```

2. Set placeholder values in `.env` (never commit `.env`).

3. **Streamlit Cloud**: copy the same keys into `.streamlit/secrets.toml` (gitignored).

| Variable | Required | Notes |
|----------|----------|-------|
| `AWS_ACCESS_KEY_ID` | For local dev | Omit when using IAM roles |
| `AWS_SECRET_ACCESS_KEY` | For local dev | |
| `AWS_DEFAULT_REGION` | Yes | e.g. `us-east-1` |
| `BEDROCK_KB_ID` | Yes | Your Knowledge Base ID |
| `BEDROCK_MODEL_ARN` | No | Defaults to Amazon Nova Pro |
| `APP_PASSWORD` | Yes | UI login gate |

The application may fall back to a development Knowledge Base ID in code if `BEDROCK_KB_ID` is unset; **always set your own KB** for sandbox or demo use.

## Run the RAG assistant

```bash
uv run streamlit run src/app.py
```

Open the URL shown in the terminal (default `http://localhost:8501`).

## Run the crawler (optional)

### CLI

```bash
uv run playwright install chromium
uv run sos-crawler crawl --states AL AR TX --mode designated --run-qa --run-enrichment
```

Outputs default to `var/sos_crawler/` (logs, downloads, manifests). Override with `SOS_CRAWLER_RUNTIME_DIR` or `--runtime-dir`.

### Distrobox (Playwright isolated)

```bash
distrobox enter playwright-distrobox
cd /path/to/AI-Innovation-Phase-1
uv sync
uv run playwright install chromium
uv run sos-crawler crawl --states AR --max-retries 0
```

### Docker

```bash
docker build -t sos-crawler .
docker run --rm \
  -v "$PWD/var/sos_crawler:/app/var/sos_crawler" \
  -e SOS_CRAWLER_RUNTIME_DIR=/app/var/sos_crawler \
  sos-crawler uv run sos-crawler crawl --states TX --max-retries 0
```

### Docker Compose

```bash
docker compose build
docker compose run --rm crawler uv run sos-crawler crawl --states AL --max-retries 0
```

## AWS Lambda note

When `AWS_LAMBDA_FUNCTION_NAME` is set, the crawler uses `/tmp/sos_crawler` unless `SOS_CRAWLER_RUNTIME_DIR` is overridden.

## Troubleshooting

- Confirm AWS region and credentials match your Bedrock KB.
- If the crawler yields zero items, check `var/sos_crawler/logs/` and Scrapy stats for drop/scope messages.
- Alabama and Texas spiders require Playwright; Arkansas and Georgia are HTTP-only.
