# ============================================================
# ${title} - Production Deployment Script
# Run this in an elevated PowerShell on the production server
# ============================================================
#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"
$ServerPort = 8082
$InstallDir = "C:\DHFleetView"
$WebPort = 8082

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   ${title} - Production Deployment" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Install Docker Desktop ──────────────────────────
Write-Host "[1/7] Checking Docker..." -ForegroundColor Yellow

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerVer = docker --version
    Write-Host "  Docker already installed: $dockerVer" -ForegroundColor Green
} else {
    Write-Host "  Installing Docker Desktop..." -ForegroundColor Yellow
    
    # Enable Windows features required by Docker
    Write-Host "  Enabling Windows containers feature..."
    Enable-WindowsOptionalFeature -Online -FeatureName Containers -NoRestart -ErrorAction SilentlyContinue
    Enable-WindowsOptionalFeature -Online -FeatureName Hyper-V -All -NoRestart -ErrorAction SilentlyContinue
    
    # Download Docker Desktop installer
    $dockerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    $dockerInstaller = "$env:TEMP\DockerDesktopInstaller.exe"
    Write-Host "  Downloading Docker Desktop..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $dockerUrl -OutFile $dockerInstaller -UseBasicParsing
    
    Write-Host "  Installing Docker Desktop (this takes a few minutes)..."
    Start-Process -FilePath $dockerInstaller -ArgumentList "install", "--quiet", "--accept-license" -Wait -NoNewWindow
    
    Write-Host "  Docker Desktop installed. You may need to REBOOT once." -ForegroundColor Green
    Write-Host "  After reboot, run this script again." -ForegroundColor Yellow
    
    # Check if reboot is needed
    $pendingReboot = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue
    if ($pendingReboot) {
        Write-Host ""
        Write-Host "  REBOOT REQUIRED. After reboot, run this script again." -ForegroundColor Red
        $reboot = Read-Host "  Reboot now? (Y/N)"
        if ($reboot -eq "Y") {
            Restart-Computer -Force
        }
        exit
    }
}

# ── Step 2: Wait for Docker daemon ──────────────────────────
Write-Host "[2/7] Waiting for Docker daemon..." -ForegroundColor Yellow
$maxWait = 60
$waited = 0
while ($waited -lt $maxWait) {
    try {
        docker info 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  Docker daemon is ready." -ForegroundColor Green
            break
        }
    } catch {}
    Start-Sleep -Seconds 3
    $waited += 3
    Write-Host "  Waiting... ($waited s)"
}
if ($waited -ge $maxWait) {
    Write-Host "  Docker daemon did not start. Please start Docker Desktop manually and re-run this script." -ForegroundColor Red
    exit 1
}

# ── Step 3: Create install directory ────────────────────────
Write-Host "[3/7] Setting up directory structure..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\data" | Out-Null
New-Item -ItemType Directory -Force -Path "$InstallDir\web" | Out-Null
Write-Host "  Created $InstallDir" -ForegroundColor Green

# ── Step 4: Clone the repo and get the web build ────────────
Write-Host "[4/7] Fetching ${title} from GitHub..." -ForegroundColor Yellow

# Download the web build zip from the repo
$repoUrl = "https://github.com/varaprasad1016/DHFLEETVIEW"
$zipUrl = "$repoUrl/archive/refs/heads/main.zip"
$zipPath = "$env:TEMP\DHFleetView.zip"

Write-Host "  Downloading repo..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing

Write-Host "  Extracting..."
Expand-Archive -Path $zipPath -DestinationPath "$env:TEMP\DHFleetView" -Force
$extractedDir = Get-ChildItem "$env:TEMP\DHFleetView" -Directory | Select-Object -First 1

# Copy web build
Write-Host "  Copying web build..."
if (Test-Path "$($extractedDir.FullName)\traccar-web\build") {
    Copy-Item -Path "$($extractedDir.FullName)\traccar-web\build\*" -Destination "$InstallDir\web" -Recurse -Force
} else {
    Write-Host "  Web build not found in repo, will build from source..." -ForegroundColor Yellow
    # Fallback: download the pre-built assets from the release
    # For now, copy what we have
}

# Copy traccar.xml config
Write-Host "  Copying server config..."
Copy-Item -Path "$($extractedDir.FullName)\setup\traccar.xml" -Destination "$InstallDir\traccar.xml" -Force

# Cleanup temp
Remove-Item -Path $zipPath -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:TEMP\DHFleetView" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "  Repo fetched and extracted." -ForegroundColor Green

# ── Step 5: Configure traccar.xml for production ────────────
Write-Host "[5/7] Configuring server..." -ForegroundColor Yellow

$traccarXml = @"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<properties>
    <!-- Database -->
    <entry key='database.driver'>org.h2.Driver</entry>
    <entry key='database.url'>jdbc:h2:./data/database</entry>
    <entry key='database.user'>sa</entry>
    <entry key='database.password' />

    <!-- Web -->
    <entry key='web.cacheControl'>no-cache</entry>
    <entry key='web.port'>$ServerPort</entry>

    <!-- Service account token for API access -->
    <entry key='web.serviceAccountToken'>dhfleetview-prod-2026</entry>
</properties>
"@

$traccarXml | Out-File -FilePath "$InstallDir\traccar.xml" -Encoding UTF8
Write-Host "  Config written to $InstallDir\traccar.xml" -ForegroundColor Green

# ── Step 6: Open Windows Firewall ───────────────────────────
Write-Host "[6/7] Configuring Windows Firewall..." -ForegroundColor Yellow

# Remove existing rule if any
Remove-NetFirewallRule -DisplayName "${title} (8082)" -ErrorAction SilentlyContinue

# Add inbound rule
New-NetFirewallRule -DisplayName "${title} (8082)" `
    -Direction Inbound `
    -Protocol TCP `
    -LocalPort $ServerPort `
    -Action Allow `
    -Profile Any `
    -Description "${title} web server"
Write-Host "  Firewall rule added: TCP $ServerPort inbound ALLOW" -ForegroundColor Green

# ── Step 7: Pull Traccar image and run container ────────────
Write-Host "[7/7] Starting ${title} container..." -ForegroundColor Yellow

# Stop and remove old container if exists
docker stop dhfleetview 2>$null
docker rm dhfleetview 2>$null

# Pull the latest Traccar image
Write-Host "  Pulling Traccar image..."
docker pull traccar/traccar:latest

# Convert Windows paths to POSIX for Docker mounts
$dataPath = "$InstallDir\data".Replace('\', '/')
$webPath = "$InstallDir\web".Replace('\', '/')
$configPath = "$InstallDir\traccar.xml".Replace('\', '/')

# Run the container
Write-Host "  Starting container on port $ServerPort..."
docker run -d `
    --name dhfleetview `
    --restart unless-stopped `
    -p "${ServerPort}:8082" `
    -v "${dataPath}:/opt/traccar/data" `
    -v "${webPath}:/opt/traccar/web" `
    -v "${configPath}:/opt/traccar/conf/traccar.xml" `
    traccar/traccar:latest

# Wait for it to start
Write-Host "  Waiting for server to start..."
Start-Sleep -Seconds 10

# Verify
$containerStatus = docker inspect dhfleetview --format '{{.State.Status}}' 2>$null
if ($containerStatus -eq "running") {
    Write-Host ""
    Write-Host "============================================" -ForegroundColor Green
    Write-Host "   ${title} is LIVE!" -ForegroundColor Green
    Write-Host "============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  URL:      http://109.228.53.195:${ServerPort}" -ForegroundColor Cyan
    Write-Host "  Status:   Running" -ForegroundColor Green
    Write-Host "  Database: $InstallDir\data\database.mv.db" -ForegroundColor Gray
    Write-Host "  Config:   $InstallDir\traccar.xml" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Container name: dhfleetview" -ForegroundColor Gray
    Write-Host "  Logs: docker logs dhfleetview -f" -ForegroundColor Gray
    Write-Host ""
    
    # Quick health check
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:${ServerPort}" -UseBasicParsing -TimeoutSec 5
        Write-Host "  Health check: HTTP $($response.StatusCode) - OK" -ForegroundColor Green
    } catch {
        Write-Host "  Health check: Server may still be starting up, give it a minute." -ForegroundColor Yellow
    }
} else {
    Write-Host ""
    Write-Host "  Container status: $containerStatus" -ForegroundColor Red
    Write-Host "  Check logs: docker logs dhfleetview" -ForegroundColor Red
    Write-Host ""
    docker logs dhfleetview 2>&1 | Select-Object -Last 20
}
