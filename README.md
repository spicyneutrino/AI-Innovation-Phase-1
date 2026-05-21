# SoS Regulation Assistant

## Overview

This repository contains the code and documentation for a Mississippi Artificial Intelligence Innovation Hub Proof of Concept focused on **multi-state Secretary of State regulatory intelligence**. The PoC was developed to explore whether retrieval-augmented generation (RAG) over administrative rules could help agency staff and researchers find, compare, and cite regulations across several southeastern states. The project demonstrates feasibility within a limited prototype environment and is **not a production-ready solution**.

## Agency Problem

Regulatory rules for dental boards, medical licensure boards, and real estate commissions are published across many state websites with different formats (PDF, HTML, DOCX, and SPA-driven portals). Staff need a single place to ask natural-language questions, see cited sources, and compare requirements between states without manually searching each code system.

## PoC Scope and Demonstrated Capabilities

- **RAG chat assistant** — Streamlit UI (`src/app.py`) queries Amazon Bedrock Knowledge Bases with citations and optional multi-turn context.
- **Automated crawler** — Scrapy + Playwright pipeline (`src/sos_crawler/`) for **MS, AL, AR, GA, LA, TN, and TX**, focused on three agency types per state.
- **State scope controls** — Sidebar checkbox grid to include or exclude states per query.
- **Post-crawl tooling** — QA and enrichment CLI for manifests and knowledge-package JSONL.
- **CI crawl workflow** — Scheduled GitHub Actions run (artifacts only; no regulatory corpora committed to git).

## Architecture Overview

See [docs/architecture.md](docs/architecture.md) for components, data flow, and a diagram of crawler → S3/KB → Streamlit.

## Repository Structure

```
├── README.md
├── LICENSE
├── .env.example
├── CHANGELOG.md
├── docs/                 # Architecture, setup, data, limitations, testing
├── src/
│   ├── app.py            # Streamlit RAG UI
│   ├── rag_engine.py     # Bedrock RetrieveAndGenerate wrapper
│   ├── style.css         # UI theme
│   └── sos_crawler/      # Crawler package (spiders, pipelines, tools)
├── scripts/              # S3 upload and metadata helpers
├── .github/workflows/    # Scheduled crawler CI
├── Dockerfile            # Crawler container (Playwright)
└── pyproject.toml        # uv / package metadata
```

Generated crawl output lives under `var/sos_crawler/` (gitignored).

## Setup

**Quick start:**

```bash
git clone https://github.com/spicyneutrino/AI-Innovation-Phase-1.git
cd AI-Innovation-Phase-1
uv sync
cp .env.example .env   # edit with your sandbox values
uv run streamlit run src/app.py
```

Full prerequisites, crawler, Docker, and troubleshooting: [docs/setup.md](docs/setup.md).

## Configuration

Copy [.env.example](.env.example) to `.env` and set:

- AWS credentials and region
- `BEDROCK_KB_ID` (required for your sandbox Knowledge Base)
- `APP_PASSWORD` (UI gate)

On Streamlit Cloud, use the same keys in `.streamlit/secrets.toml` (not committed). Do not commit real secrets or production resource IDs you cannot rotate.

## Data Notes

**This repository does not include real data.** Any future samples would be placeholder or illustrative only.

Indexing, S3 layout, and Bedrock sync are operator responsibilities. Details: [docs/data-notes.md](docs/data-notes.md).

## Usage

1. Start the app: `uv run streamlit run src/app.py`
2. Sign in with the configured password.
3. Use the **Scope** sidebar to select states (or clear all to search the full knowledge base without a state filter).
4. Ask questions in the chat or use the suggested prompts on the welcome screen.

**Optional — run the crawler:**

```bash
uv run playwright install chromium
uv run sos-crawler crawl --states MS AL AR --mode designated --run-qa --run-enrichment
```

## Testing and Evaluation

Manual validation steps, sample evaluation queries, and CI notes: [docs/testing.md](docs/testing.md).

## Limitations

This PoC was developed within a limited timeline and controlled environment. It may contain simplified workflows, mock integrations, limited testing coverage, and prototype user interfaces.

See [docs/limitations.md](docs/limitations.md) for security, scope, and production gaps.

## Disclaimer

This repository contains code and supporting materials developed as part of a Mississippi Artificial Intelligence Innovation Hub Proof of Concept project. The contents are provided for prototype demonstration purposes. They are not production ready by default and may include simplified workflows, incomplete security guardrails, placeholder integrations, or reduced controls appropriate only for a Proof-of-Concept environment.

Do not use this software with production data or in production environments without additional architecture, security, privacy, testing, and stakeholder review.

## License

Released under the [MIT License](LICENSE).

## Contributors

**SoS Innovation Hub Team** (placeholder — update with final attribution before Hub sign-off).
