FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unixodbc unixodbc-dev gcc g++ \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb -o /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && apt-get purge -y --auto-remove curl gcc g++ unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace/backend/uta_sumo_api
COPY backend/uta_sumo_api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/uta_sumo_api/ ./
COPY database/ /workspace/database/

RUN groupadd --system app && useradd --system --gid app --home-dir /workspace/backend/uta_sumo_api app \
    && mkdir -p /app/storage/receipts /app/storage/regulations \
    && chown -R app:app /app/storage /workspace

USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
