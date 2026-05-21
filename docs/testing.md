# Testing and evaluation

This repository does not include a full automated test suite. Validation is **manual** and focused on crawler output quality and RAG behavior in a sandbox.

## Crawler validation

After a crawl:

```bash
uv run sos-crawler qa
```

Review manifests under `var/sos_crawler/output/`:

- Citations, `extracted_text` length, `agency`, and `state` fields populated
- Scrapy logs under `var/sos_crawler/logs/` for `item_scraped_count` and `DropItem` messages

Example spot-check:

```bash
cat var/sos_crawler/output/manifest_arkansas_$(date +%Y%m%d).jsonl | python3 -c "
import sys, json
for line in sys.stdin:
    r = json.loads(line)
    print(r.get('citation'), r.get('size_bytes'))
"
```

## RAG assistant validation

1. Configure `.env` or Streamlit secrets with a sandbox Knowledge Base.
2. Run `uv run streamlit run src/app.py`.
3. Log in with `APP_PASSWORD`.
4. Try the suggested prompts on the welcome screen (dental, real estate, medical, cross-state comparison).
5. Confirm:
   - Answers cite retrieved sources
   - State scope checkboxes filter behavior as expected
   - Empty state selection searches without a metadata filter (full KB)

## Evaluation queries (examples)

| Topic | Sample question |
|-------|-----------------|
| Dental | Can a dental assistant monitor a patient under nitrous oxide in Mississippi? |
| Real estate | What are the continuing education hour requirements for a real estate broker in Louisiana? |
| Medical | What are the biennial renewal and expiration date rules for a medical license in Georgia? |
| Comparison | Compare the real estate broker renewal hours between Louisiana and Mississippi. |

Record observed strengths (citation coverage, multi-state comparisons) and gaps (missing states in index, hallucination risk) in your Hub closeout notes.

## CI

GitHub Actions (`.github/workflows/crawl.yml`) runs a scheduled crawl and uploads artifacts. It does not publish crawl data to the public repository.
