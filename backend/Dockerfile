FROM python:3.13-slim

WORKDIR /app

# postgresql-client provides pg_dump, used by services/backup.py
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# s5cmd: optional upload engine (Settings → Upload → Upload engine)
COPY --from=peakcom/s5cmd:v2.3.0 /s5cmd /usr/local/bin/s5cmd

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
