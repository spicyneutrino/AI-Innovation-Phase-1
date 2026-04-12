FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

RUN apt-get update && apt-get install -y \
    g++ make cmake unzip libcurl4-openssl-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN pip install --no-cache-dir uv
RUN uv python install 3.12

# 1. Copy metadata
COPY pyproject.toml uv.lock README.md ./

# 2. COPY THE SOURCE CODE NOW (Required for uv sync to find the 'src' dir)
COPY src/ ./src/
COPY scrapy.cfg ./
COPY lambda_handler.py ./

# 3. Now run the sync
RUN uv sync --frozen --python 3.12 && \
    uv pip install awslambdaric

# 4. Download the RIE
ADD https://github.com/aws/aws-lambda-runtime-interface-emulator/releases/latest/download/aws-lambda-rie /usr/bin/aws-lambda-rie
RUN chmod 755 /usr/bin/aws-lambda-rie

ENV SOS_CRAWLER_RUNTIME_DIR=/tmp/sos_crawler
ENV PLAYWRIGHT_HEADLESS=true
ENV PYTHONPATH=/app:/app/src
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /tmp/sos_crawler

RUN echo '#!/bin/sh\n\
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then\n\
  exec /usr/bin/aws-lambda-rie uv run python -m awslambdaric lambda_handler.handler\n\
else\n\
  exec uv run python -m awslambdaric lambda_handler.handler\n\
fi' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT [ "/app/entrypoint.sh" ]