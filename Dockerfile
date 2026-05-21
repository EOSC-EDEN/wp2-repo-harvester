FROM python:3.12-slim AS base

LABEL org.opencontainers.image.title="EDEN Repository Harvester"
LABEL org.opencontainers.image.description="Harvests metadata from research data repositories and stores it as DCAT JSON-LD in Apache Jena Fuseki"
LABEL org.opencontainers.image.source="https://github.com/EOSC-EDEN/wp2-repo-harvester"
LABEL org.opencontainers.image.vendor="EOSC-EDEN"
LABEL org.opencontainers.image.licenses="Apache-2.0"

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

FROM base AS deps

RUN python -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS production

COPY --from=deps /app/venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY . .

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/ui/')" || exit 1

CMD ["python", "main.py"]
