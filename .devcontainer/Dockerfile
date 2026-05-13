FROM python:3.10-slim
WORKDIR /workspace
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Port 透過 docker-compose 或 run_server.py 動態設定
CMD ["python", "run_server.py"]