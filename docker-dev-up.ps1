# Start development environment with docker-compose
# This uses docker-compose.dev.yml which mounts source code for hot-reload

Write-Host "Starting DreamGen development environment..." -ForegroundColor Green
Write-Host ""

# Check if services are already running
$running = docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps --quiet 2>$null
if ($running) {
    Write-Host "Services are already running. Stopping them first..." -ForegroundColor Yellow
    docker-compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.docker down
}

Write-Host "Building and starting services..." -ForegroundColor Cyan
docker-compose -f docker-compose.yml -f docker-compose.dev.yml --env-file .env.docker up -d --build

Write-Host ""
Write-Host "Waiting for services to start..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "Service Status:" -ForegroundColor Green
docker-compose -f docker-compose.yml -f docker-compose.dev.yml ps

Write-Host ""
Write-Host "Services are starting!" -ForegroundColor Green
Write-Host ""
Write-Host "Access the application:" -ForegroundColor Yellow
Write-Host "  Frontend:  http://localhost:7860" -ForegroundColor White
Write-Host "  Backend:   http://localhost:8001" -ForegroundColor White
Write-Host "  API Status: http://localhost:8001/api/status" -ForegroundColor White
Write-Host ""
Write-Host "View logs with:" -ForegroundColor Yellow
Write-Host "  docker logs -f imagegen-backend" -ForegroundColor White
Write-Host "  docker logs -f imagegen-frontend" -ForegroundColor White
Write-Host ""
Write-Host "Stop services with:" -ForegroundColor Yellow
Write-Host "  docker-compose -f docker-compose.yml -f docker-compose.dev.yml down" -ForegroundColor White
