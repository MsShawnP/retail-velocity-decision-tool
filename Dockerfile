FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN git clone --depth 1 https://github.com/MsShawnP/cinderhaven-data.git data/cinderhaven-data

RUN pip install --no-cache-dir -r data/cinderhaven-data/requirements.txt

RUN python data/cinderhaven-data/scripts/build_db.py --output data/cinderhaven_product_master.db

EXPOSE 8501

CMD ["streamlit", "run", "app/velocity_tool.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
