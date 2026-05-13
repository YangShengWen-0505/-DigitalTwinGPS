@echo off
echo [SYSTEM] Stopping and cleaning old containers...
docker-compose -f .devcontainer/docker-compose.yml down

echo [SYSTEM] Starting server with latest .env settings...
docker-compose -f .devcontainer/docker-compose.yml up -d --build --force-recreate

echo [SYSTEM] Current Docker Status:
docker ps --format "table {{.Names}}\t{{.Ports}}"
pause
