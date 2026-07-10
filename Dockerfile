FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

# Ship the pre-baked serving artifacts. data.py resolves _BAKED_DIR to
# Path(__file__).parent.parent/data/baked_views -> /data/baked_views in-image.
# Without this, the app silently falls back to live Postgres for every view.
COPY data/baked_views /data/baked_views

EXPOSE 8080

CMD ["gunicorn", "run:server", \
     "-b", "0.0.0.0:8080", \
     "-w", "1", \
     "--worker-class", "gthread", \
     "--threads", "4", \
     "--timeout", "120"]
