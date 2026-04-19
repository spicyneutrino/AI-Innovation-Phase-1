FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

RUN apt-get update && apt-get install -y \
    g++ make cmake unzip libcurl4-openssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv
RUN pip install --no-cache-dir uv
RUN uv python install 3.12

# 1. Copy metadata
COPY pyproject.toml uv.lock README.md ./

# 2. Copy the source code
COPY src/ ./src/
COPY scrapy.cfg ./
# (If you have a main.py or run.py to start the crawler, copy it here)

# 3. Sync dependencies (Notice we removed awslambdaric)
RUN uv sync --frozen --python 3.12

# 4. Set Environment Variables
ENV SOS_CRAWLER_RUNTIME_DIR=/tmp/sos_crawler
ENV PLAYWRIGHT_HEADLESS=true
ENV PYTHONPATH=/app:/app/src
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /tmp/sos_crawler

# 5. Execute the crawler
# Replace 'main.py' with whatever script actually starts your spiders
CMD ["uv", "run", "sos-crawler", "crawl", "--states", "GA", "TN", "LA", "MS", "AR", "TX", "AL"]
