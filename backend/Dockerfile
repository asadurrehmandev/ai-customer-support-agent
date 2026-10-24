FROM python:3.12-slim

WORKDIR /srv

COPY backend/pyproject.toml /srv/pyproject.toml
COPY backend/app /srv/app

RUN pip install --no-cache-dir .

ENV FASTEMBED_CACHE_PATH=/var/cache/fastembed \
    KEEL_DATABASE_URL=sqlite:////data/keel.db \
    PYTHONUNBUFFERED=1

EXPOSE 8841

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8841"]
