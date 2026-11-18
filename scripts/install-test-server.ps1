
$ErrorActionPreference = "Stop"

# ==========================================
# MCSync test server configuration
# ==========================================

$ProjectRoot = "D:\DATA\GITHUB PROJECTS\MCSync"
$ServerFolder = Join-Path $ProjectRoot "test-server"

$MinecraftVersion = "1.21.1"
$NeoForgeVersion = "21.1.252"

$InstallerName = "neoforge-$NeoForgeVersion-installer.jar"
$InstallerUrl = "https://maven.neoforged.net/releases/net/neoforged/neoforge/$NeoForgeVersion/$InstallerName"

# ==========================================
# Find Java 21
# ==========================================

Write-Host ""
Write-Host "Searching for Java 21..."

$JavaExe = $null

# First look for Eclipse Temurin 21 in its normal install directory.
$AdoptiumFolder = Join-Path $env:ProgramFiles "Eclipse Adoptium"

if (Test-Path $AdoptiumFolder) {
    $JdkFolders = Get-ChildItem $AdoptiumFolder -Directory |
        Where-Object { $_.Name -like "jdk-21*" } |
        Sort-Object Name -Descending

    foreach ($Folder in $JdkFolders) {
        $Candidate = Join-Path $Folder.FullName "bin\java.exe"

        if (Test-Path $Candidate) {
            $JavaExe = $Candidate
            break
        }
    }
}

# Fall back to Java available on PATH, but only if it is version 21.
if (!$JavaExe) {
    $PathJava = Get-Command java -ErrorAction SilentlyContinue

    if ($PathJava) {
        $VersionOutput = (& $PathJava.Source -version 2>&1 | Out-String)

        if ($VersionOutput -match 'version "21\.') {
            $JavaExe = $PathJava.Source
        }
    }
}

if (!$JavaExe) {
    throw "Could not locate Java 21. Check your Eclipse Temurin installation."
}

$PreviousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"

try {
    $JavaVersion = (& $JavaExe -version 2>&1 | Out-String)
}
finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
}

if ($JavaVersion -notmatch 'version "21\.') {
    throw "The selected Java executable is not Java 21: $JavaExe"
}

Write-Host "Java 21 found:"
Write-Host $JavaExe
Write-Host $JavaVersion

# Use Java 21 for this PowerShell session and the test server.
$env:JAVA_HOME = Split-Path (Split-Path $JavaExe -Parent) -Parent
$env:PATH = "$(Split-Path $JavaExe -Parent);$env:PATH"

# ==========================================
# Create project directories
# ==========================================

Write-Host "Creating project directories..."

New-Item -ItemType Directory -Force -Path $ProjectRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ServerFolder | Out-Null

Set-Location $ServerFolder

# Do not overwrite an existing server installation.
if (Test-Path "run.bat") {
    throw "A server installation already exists. Refusing to overwrite it."
}

# ==========================================
# Download NeoForge installer
# ==========================================

Write-Host ""
Write-Host "Downloading NeoForge $NeoForgeVersion..."

if (!(Test-Path $InstallerName)) {
    Invoke-WebRequest -Uri $InstallerUrl -OutFile $InstallerName
} else {
    Write-Host "Installer already exists; reusing it."
}

# ==========================================
# Install server
# ==========================================

Write-Host ""
Write-Host "Installing NeoForge server..."

& $JavaExe -jar $InstallerName --installServer

if ($LASTEXITCODE -ne 0) {
    throw "NeoForge installation failed."
}

if (!(Test-Path "run.bat")) {
    throw "NeoForge installer did not create run.bat."
}

# ==========================================
# Create test server folders
# ==========================================

New-Item -ItemType Directory -Force -Path "mods" | Out-Null
New-Item -ItemType Directory -Force -Path "config" | Out-Null
New-Item -ItemType Directory -Force -Path "defaultconfigs" | Out-Null

# ==========================================
# Configure isolated test server
# ==========================================

@"
# MCSync isolated test server
level-name=MCSyncTest
server-port=25566
server-ip=
online-mode=true
enable-rcon=false
motd=MCSync Test Server
max-players=5
view-distance=8
simulation-distance=6
"@ | Set-Content -Encoding ASCII "server.properties"

# ==========================================
# Save installation information
# ==========================================

$InstallInfo = @{
    minecraft_version = $MinecraftVersion
    neoforge_version = $NeoForgeVersion
    java_executable = $JavaExe
    server_folder = $ServerFolder
    world_name = "MCSyncTest"
    server_port = 25566
    created_at = (Get-Date).ToString("o")
}

$InstallInfo |
    ConvertTo-Json -Depth 5 |
    Set-Content -Encoding UTF8 "mcsync-install.json"

# ==========================================
# Complete
# ==========================================

Write-Host ""
Write-Host "=========================================="
Write-Host "MCSync TEST SERVER INSTALLED"
Write-Host "=========================================="
Write-Host "Project:       $ProjectRoot"
Write-Host "Server:        $ServerFolder"
Write-Host "Minecraft:     $MinecraftVersion"
Write-Host "NeoForge:      $NeoForgeVersion"
Write-Host "Java:          $JavaExe"
Write-Host "World:         MCSyncTest"
Write-Host "Port:          25566"
Write-Host ""
Write-Host "IMPORTANT: Do not start the server yet."
Write-Host "We still need to transfer your modpack files."
Write-Host "Your existing EC2 world has not been copied."
