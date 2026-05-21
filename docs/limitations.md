# Limitations

This Proof of Concept was developed within a limited timeline and controlled environment. It may contain simplified workflows, mock integrations, limited testing coverage, and prototype user interfaces.

## Functional scope

- **Not production-ready** — additional security, privacy, testing, and stakeholder review are required before any production use.
- **Password gate only** — the Streamlit UI uses a single shared password (`APP_PASSWORD`); there is no enterprise identity integration.
- **Manual knowledge base sync** — S3 upload and Bedrock KB indexing are operator-driven; the repo does not include full CI/CD for indexing.
- **Partial state coverage** — only seven states and three agency types per state are in scope; other agencies and rules are excluded.
- **Citation fidelity** — answers depend on indexed content; missing or stale index data produces incomplete or empty citations.
- **No automated test suite** — validation is manual (crawler QA tool, spot-check RAG queries).

## Technical constraints

- Crawler reliability varies by site (SPAs require Playwright; rate limits and DOM changes can break spiders).
- Large comparison questions may still be limited by retrieval chunk count (configured to 20 results per query).
- Georgia, Louisiana, and Tennessee implementations may differ in URL granularity (chapter-level vs rule-level).
- Default `BEDROCK_KB_ID` in code is a development fallback; operators must configure their own KB for sandbox demos.

## Security and compliance

- Do not use production agency data in shared sandboxes without approval.
- Rotate any credential that was ever committed or logged.
- Guardrails in the LLM prompt are instructional only; they are not a substitute for policy review or legal counsel.

## Out of scope

- Production HA, monitoring, audit logging, or role-based access control
- Official legal interpretation or filing advice
- Guaranteed parity with each state's official code publication systems
