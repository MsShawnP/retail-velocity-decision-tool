FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

EXPOSE 8080

CMD ["gunicorn", "run:server", \
     "-b", "0.0.0.0:8080", \
     "-w", "2", \
     "--worker-class", "gthread", \
     "--threads", "2", \
     "--timeout", "60"]
