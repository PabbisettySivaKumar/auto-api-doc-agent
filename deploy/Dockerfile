FROM python:3.12-slim

# git is required: the pipeline clones each repo to diff it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# Host platforms (Railway/Render/Fly) inject $PORT.
CMD ["sh", "-c", "uvicorn service.webhook:app --host 0.0.0.0 --port ${PORT}"]
