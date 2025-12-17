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

## Troubleshooting
- Ensure your AWS credentials and region are set correctly.
- If commands fail, confirm `uv` is installed and available in your PATH.


