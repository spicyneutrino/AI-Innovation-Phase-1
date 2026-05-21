# Data notes

## What is not in this repository

This repository **does not include real regulatory data**, production databases, or live agency exports.

Per Innovation Hub publication guidance:

- Do not expect downloadable rule corpora in git.
- Any future samples must be **synthetic or illustrative** only.

## Where data lives at runtime

| Location | Contents |
|----------|----------|
| `var/sos_crawler/` | Generated crawler output (gitignored): downloads, manifests, logs, cache |
| Operator S3 bucket | Indexed documents for Bedrock (configured outside this repo) |
| Bedrock Knowledge Base | Vector index (OpenSearch Serverless in typical setups) |

## States and agencies

The crawler targets three agency types per state where available:

- **Dental** examiners / boards
- **Medical licensure** boards
- **Real estate** commissions

Configured states: **MS, AL, AR, GA, LA, TN, TX**. Mississippi is the primary reference for metadata and citation URL patterns.

## Indexing workflow (operator responsibility)

1. Run `sos-crawler crawl` (and optional `--run-enrichment`).
2. Upload text/metadata to S3 using your approved pipeline (`scripts/upload_to_s3.py`, `s3_uploader.py`, or internal automation).
3. Sync the Bedrock Knowledge Base so the RAG assistant can retrieve new documents.

This PoC does not automate KB sync in the committed codebase; that remains a manual or separate Phase 2 step.

## Screenshots and demos

Store redacted UI screenshots under `docs/images/` when available. Do not commit images that contain real user data, credentials, or identifiable records.
