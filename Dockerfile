FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN git clone https://github.com/MsShawnP/cinderhaven-data.git data/cinderhaven-data \
    && cd data/cinderhaven-data \
    && git checkout 4f1ae9128eeed6afbcd5ae4274ee03e031af5509 \
    && cd /app

RUN pip install --no-cache-dir -r data/cinderhaven-data/requirements.txt

# Remove deduction pipeline steps (scripts 07-15) that don't exist at the pinned commit
RUN sed -i '/# Deduction pipeline/,/"15_validate_deductions.py",/d' data/cinderhaven-data/scripts/build_db.py

RUN python data/cinderhaven-data/scripts/build_db.py --output data/cinderhaven_product_master.db

EXPOSE 8501

CMD ["streamlit", "run", "app/velocity_tool.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
