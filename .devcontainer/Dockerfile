FROM python:3.10-slim

WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Keep the Dev Container idle. Start the app manually in VS Code:
# python run_server.py
CMD ["sleep", "infinity"]
