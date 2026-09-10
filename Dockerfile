FROM python:3.12-slim

WORKDIR /srv

# System deps kept minimal; add pcsc/libs only if card logic ever moves here
# (it does not — the forked TBA owns all PC/SC access).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Optional MIT tachograph-go reader. Keeping the binary in the image makes the
# Go parser the default in production; TACHO_PARSER_FALLBACK controls whether
# the legacy Gen1 Python reader may be used if it rejects a file.
ARG TACHOGRAPH_GO_VERSION=v0.18.2
ARG TARGETARCH
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) goarch=amd64 ;; \
      arm64) goarch=arm64 ;; \
      *) echo "Unsupported target architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    archive="tachograph-go_0.18.2_linux_${goarch}.tar.gz"; \
    url="https://github.com/way-platform/tachograph-go/releases/download/${TACHOGRAPH_GO_VERSION}/${archive}"; \
    mkdir -p /tmp/tachograph-go; \
    curl -fsSL "$url" -o "/tmp/tachograph-go/${archive}"; \
    tar -xzf "/tmp/tachograph-go/${archive}" -C /tmp/tachograph-go; \
    install -m 0755 /tmp/tachograph-go/tachograph /usr/local/bin/tachograph; \
    rm -rf /tmp/tachograph-go

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000 29000 21756 8765

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
