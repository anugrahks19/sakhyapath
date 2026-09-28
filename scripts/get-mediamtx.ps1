$ErrorActionPreference = 'Stop'
$release = 'v1.21.1'
$archiveName = 'mediamtx_v1.21.1_windows_amd64.zip'
$baseUrl = "https://github.com/bluenviron/mediamtx/releases/download/$release"
$toolsDir = Join-Path $PSScriptRoot '..\backend\data\tools'
New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$archive = Join-Path $toolsDir $archiveName
$checksums = Join-Path $toolsDir 'checksums.sha256'
Invoke-WebRequest -Uri "$baseUrl/$archiveName" -OutFile $archive
Invoke-WebRequest -Uri "$baseUrl/checksums.sha256" -OutFile $checksums
$line = Select-String -LiteralPath $checksums -Pattern ([regex]::Escape($archiveName)) | Select-Object -First 1
if (-not $line) { throw 'MediaMTX archive not found in the published checksums' }
$expected = ($line.Line -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expected -ne $actual) { throw 'MediaMTX SHA-256 verification failed' }
$destination = Join-Path $toolsDir 'mediamtx'
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
Write-Output "Verified MediaMTX $release at $destination"
