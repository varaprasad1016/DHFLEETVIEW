FROM python:3.12-slim

WORKDIR /srv

# System deps kept minimal; add pcsc/libs only if card logic ever moves here
# (it does not — the forked TBA owns all PC/SC access).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 29000 21756 8765

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
