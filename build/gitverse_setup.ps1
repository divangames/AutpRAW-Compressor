# Создаёт репозиторий AutoRAWCompressor на GitVerse (если есть GITVERSE_TOKEN) и пушит master.
param(
    [string]$Token = $env:GITVERSE_TOKEN,
    [string]$Owner = "delbraun",
    [string]$Name = "AutoRAWCompressor"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "safe.directory"
$env:GIT_CONFIG_VALUE_0 = $Root

if (-not $Token) {
    Write-Host "GITVERSE_TOKEN not set."
    Write-Host "Create token: GitVerse -> Settings -> Token management -> Repositories + Public API"
    Write-Host "Then: setx GITVERSE_TOKEN ""your_token"""
    Write-Host "Or create repo manually: https://gitverse.ru/new (name: AutoRAWCompressor, empty)"
    exit 1
}

$headers = @{
    Authorization = "Bearer $Token"
    Accept        = "application/vnd.gitverse.object+json;version=1"
}
$body = @{
    name        = $Name
    description = "AutoRAW Compressor — автокадрирование RAW (Python prototype)"
    private     = $true
    auto_init   = $false
} | ConvertTo-Json

try {
    $repo = Invoke-RestMethod -Method POST -Uri "https://api.gitverse.ru/user/repos" -Headers $headers -Body $body -ContentType "application/json"
    Write-Host "Created: $($repo.html_url)"
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 422) {
        Write-Host "Repository $Owner/$Name already exists."
    } else {
        throw
    }
}

$url = "https://gitverse.ru/$Owner/$Name.git"
if (-not (git remote | Select-String -Pattern '^gitverse$' -Quiet)) {
    git remote add gitverse $url
} else {
    git remote set-url gitverse $url
}

git push -u gitverse master
Write-Host "Done: https://gitverse.ru/$Owner/$Name"
