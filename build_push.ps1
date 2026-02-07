# Build and push docker image
$ErrorActionPreference = "Stop"

$Image = "alanwakeking/telegramm_bot:latest"

Write-Host "Building $Image" -ForegroundColor Cyan
& docker build -t $Image .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Pushing $Image" -ForegroundColor Cyan
& docker push $Image
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Done" -ForegroundColor Green
