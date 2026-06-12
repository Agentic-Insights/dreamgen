param(
    [string]$ApiBase = "http://127.0.0.1:25800",
    [string]$UiBase = "http://127.0.0.1:7860",
    [string[]]$AlsoCheckApiBases = @("http://localhost:25800"),
    [string[]]$ExpectedRoutes = @("/api/compare"),
    [string[]]$ForbiddenRoutes = @("/api/batch", "/api/edit"),
    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = "Stop"

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$apiStatus = $null
$uiResponse = $null

while ((Get-Date) -lt $deadline) {
    try {
        $apiStatus = Invoke-RestMethod "$ApiBase/api/status" -TimeoutSec 3
    } catch {
        $apiStatus = $null
    }

    try {
        $uiResponse = Invoke-WebRequest $UiBase -UseBasicParsing -TimeoutSec 3
    } catch {
        $uiResponse = $null
    }

    if ($apiStatus -and $uiResponse -and $uiResponse.StatusCode -lt 500) {
        break
    }

    Start-Sleep -Seconds 2
}

if (-not $apiStatus) {
    throw "API did not become healthy at $ApiBase/api/status"
}

if (-not $uiResponse -or $uiResponse.StatusCode -ge 500) {
    throw "UI did not become healthy at $UiBase"
}

$openapi = Invoke-RestMethod "$ApiBase/openapi.json" -TimeoutSec 10
$routes = @($openapi.paths.PSObject.Properties.Name)

foreach ($route in $ExpectedRoutes) {
    if ($routes -notcontains $route) {
        throw "Expected route is missing from running API: $route"
    }
}

foreach ($route in $ForbiddenRoutes) {
    if ($routes -contains $route) {
        throw "Forbidden stale route is still present in running API: $route"
    }
}

foreach ($extraApiBase in $AlsoCheckApiBases) {
    if ($extraApiBase.TrimEnd("/") -eq $ApiBase.TrimEnd("/")) {
        continue
    }

    $extraOpenapi = Invoke-RestMethod "$extraApiBase/openapi.json" -TimeoutSec 10
    $extraRoutes = @($extraOpenapi.paths.PSObject.Properties.Name)

    foreach ($route in $ExpectedRoutes) {
        if ($extraRoutes -notcontains $route) {
            throw "Expected route is missing from alternate API base ${extraApiBase}: $route"
        }
    }

    foreach ($route in $ForbiddenRoutes) {
        if ($extraRoutes -contains $route) {
            throw "Forbidden stale route is present at alternate API base ${extraApiBase}: $route"
        }
    }
}

Write-Host "DreamGen live check passed."
Write-Host "  UI: $UiBase"
Write-Host "  API: $ApiBase/api/status"
foreach ($extraApiBase in $AlsoCheckApiBases) {
    if ($extraApiBase.TrimEnd("/") -ne $ApiBase.TrimEnd("/")) {
        Write-Host "  Also checked API: $extraApiBase"
    }
}
Write-Host "  Backend: $($apiStatus.backend)"
