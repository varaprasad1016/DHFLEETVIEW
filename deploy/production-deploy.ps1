# ${title} - Production Deployment Script
# Run this in PowerShell (Admin) on the production server
# Server: 109.228.53.195

$ErrorActionPreference = "Stop"

Write-Host "=== ${title} Production Deployment ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install Docker if not present
$dockerInstalled = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerInstalled) {
    Write-Host "[1/6] Installing Docker Desktop..." -ForegroundColor Yellow
    
    # Check if Windows containers feature is enabled
    $feature = Get-WindowsOptionalFeature -Online -FeatureName Containers
    if ($feature.State -ne "Enabled") {
        Write-Host "  Enabling Containers feature..."
        Enable-WindowsOptionalFeature -Online -FeatureName Containers -NoRestart
    }
    
    $feature = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V
    if ($feature.State -ne "Enabled") {
        Write-Host "  Enabling Hyper-V feature..."
        Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -NoRestart
    }
    
    # Download and install Docker CE
    $dockerUrl = "https://download.docker.com/win/static/stable/x86_64/"
    $latestVersion = Invoke-WebRequest -Uri $dockerUrl -UseBasicParsing | Select-Object -ExpandProperty Links | Where-Object { $_.href -match "docker-\d" } | Sort-Object -Property href -Descending | Select-Object -First 1
    $dockerInstaller = Join-Path $env:TEMP "docker-desktop-installer.exe"
    
    Write-Host "  Downloading Docker Desktop..."
    Invoke-WebRequest -Uri "$($dockerUrl)$($latestVersion.href)" -OutFile $dockerInstaller
    
    Write-Host "  Installing Docker Desktop (this may take a few minutes)..."
    Start-Process -FilePath $dockerInstaller -ArgumentList "install", "--quiet", "--accept-license" -Wait
    
    Write-Host "  Docker installed. You may need to restart the server." -ForegroundColor Green
    Write-Host "  After restart, re-run this script to continue deployment." -ForegroundColor Yellow
    exit
}

Write-Host "[1/6] Docker is installed" -ForegroundColor Green

# Step 2: Ensure Docker is running
$dockerRunning = Get-Service -Name "com.docker.service" -ErrorAction SilentlyContinue
if ($dockerRunning -and $dockerRunning.Status -ne "Running") {
    Write-Host "[2/6] Starting Docker service..."
    Start-Service "com.docker.service"
    Start-Sleep -Seconds 10
} else {
    Write-Host "[2/6] Docker is running" -ForegroundColor Green
}

# Step 3: Create deployment directory
$deployDir = "C:\DHFleetView"
if (-not (Test-Path $deployDir)) {
    Write-Host "[3/6] Creating deployment directory..."
    New-Item -ItemType Directory -Path $deployDir -Force | Out-Null
} else {
    Write-Host "[3/6] Deployment directory exists" -ForegroundColor Green
}

# Step 4: Download the project from GitHub
Write-Host "[4/6] Downloading ${title} from GitHub..."
$zipUrl = "https://github.com/varaprasad1016/DHFLEETVIEW/archive/refs/heads/main.zip"
$zipFile = Join-Path $env:TEMP "dhfleetview.zip"

# Download
Invoke-WebRequest -Uri $zipUrl -OutFile $zipFile -UseBasicParsing

# Extract
Expand-Archive -Path $zipFile -DestinationPath $deployDir -Force

# Move contents from the subdirectory to root
$extractedDir = Join-Path $deployDir "DHFLEETVIEW-main"
if (Test-Path $extractedDir) {
    Copy-Item -Path "$extractedDir\*" -Destination $deployDir -Recurse -Force
    Remove-Item -Path $extractedDir -Recurse -Force
}

Write-Host "  Project downloaded" -ForegroundColor Green

# Step 5: Create server config
Write-Host "[5/6] Creating server configuration..."
$configDir = Join-Path $deployDir "conf"
if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

$configXml = @"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<properties>
    <entry key='database.driver'>org.h2.Driver</entry>
    <entry key='database.url'>jdbc:h2:./data/database</entry>
    <entry key='database.user'>sa</entry>
    <entry key='database.password' />
    <entry key='web.cacheControl'>no-cache</entry>
    <entry key='registration.enable'>false</entry>
</properties>
"@

Set-Content -Path (Join-Path $configDir "traccar.xml") -Value $configXml

# Create web and data directories
$webDir = Join-Path $deployDir "web"
$dataDir = Join-Path $deployDir "data"
if (-not (Test-Path $webDir)) { New-Item -ItemType Directory -Path $webDir -Force | Out-Null }
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }

Write-Host "  Configuration created" -ForegroundColor Green

# Step 6: Stop old container and start new one
Write-Host "[6/6] Starting ${title} server..."

# Stop existing container if running
$existing = docker ps -a --filter "name=dhfleetview" --format "{{.Names}}"
if ($existing) {
    docker stop dhfleetview 2>$null
    docker rm dhfleetview 2>$null
}

# Pull the latest image
docker pull traccar/traccar:latest

# Start the container
$webPath = $webDir -replace '\\', '/'
$configPath = (Join-Path $configDir "traccar.xml") -replace '\\', '/'
$dataPath = $dataDir -replace '\\', '/'

docker run -d `
    --name dhfleetview `
    --restart unless-stopped `
    -p 8082:8082 `
    -p 5027:5027 `
    -v "${webPath}:/opt/traccar/web" `
    -v "${configPath}:/opt/traccar/conf/traccar.xml:ro" `
    -v "${dataPath}:/opt/traccar/data" `
    traccar/traccar:latest

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Access ${title} at: http://109.228.53.195:8082" -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: You may need to open port 8082 in Windows Firewall:" -ForegroundColor Yellow
Write-Host '  netsh advfirewall firewall add rule name="${title} HTTP" dir=in action=allow protocol=TCP localport=8082' -ForegroundColor White
Write-Host ""
Write-Host "And in the IONOS cloud firewall/security group, allow inbound TCP 8082" -ForegroundColor Yellow
Write-Host ""
Write-Host "Also open port 5027 for GPS device tracking:" -ForegroundColor Yellow
Write-Host '  netsh advfirewall firewall add rule name="${title} GPS" dir=in action=allow protocol=TCP localport=5027' -ForegroundColor White
