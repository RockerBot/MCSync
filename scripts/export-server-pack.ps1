
param(
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"

# Resolve the repository relative to this script.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ServerRoot = Join-Path $ProjectRoot "test-server"

if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Split-Path -Parent $ProjectRoot) "MCSync-ServerPack"
}

$PackName = "MCSync-ServerPack-MC-1.21.1-NeoForge-21.1.252"
$ZipPath = Join-Path $OutputDirectory "$PackName.zip"
$HashPath = "$ZipPath.sha256"

$RequiredDirectories = @(
    "mods",
    "libraries",
    "config",
    "defaultconfigs"
)

$RequiredFiles = @(
    "eula.txt",
    "ops.json",
    "server.properties",
    "user_jvm_args.txt"
)

Write-Host "`nMCSync Server Pack Export" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"
Write-Host "Server:  $ServerRoot"
Write-Host "Output:  $OutputDirectory"

if (-not (Test-Path $ServerRoot -PathType Container)) {
    throw "Server directory not found: $ServerRoot"
}

foreach ($directory in $RequiredDirectories) {
    $path = Join-Path $ServerRoot $directory
    if (-not (Test-Path $path -PathType Container)) {
        throw "Required server directory missing: $path"
    }
}

foreach ($file in $RequiredFiles) {
    $path = Join-Path $ServerRoot $file
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "Required server file missing: $path"
    }
}

$NeoForgeArgs = Join-Path $ServerRoot `
    "libraries\net\neoforged\neoforge\21.1.252\win_args.txt"

if (-not (Test-Path $NeoForgeArgs -PathType Leaf)) {
    throw "NeoForge launch arguments not found: $NeoForgeArgs"
}

$EulaText = Get-Content (Join-Path $ServerRoot "eula.txt") -Raw
if ($EulaText -notmatch '(?m)^eula=true\s*$') {
    throw "EULA is not set to true. Review and accept the Minecraft EULA before exporting."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$StageRoot = Join-Path $env:TEMP ("MCSync-Pack-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $StageRoot | Out-Null

try {
    Write-Host "`nCopying server files..."

    foreach ($directory in $RequiredDirectories) {
        Copy-Item -LiteralPath (Join-Path $ServerRoot $directory) `
            -Destination $StageRoot -Recurse
        Write-Host "  Included directory: $directory"
    }

    foreach ($file in $RequiredFiles) {
        Copy-Item -LiteralPath (Join-Path $ServerRoot $file) `
            -Destination $StageRoot
        Write-Host "  Included file: $file"
    }

    $Info = @"
MCSync Server Pack
==================

Minecraft: 1.21.1
Mod loader: NeoForge 21.1.252

This pack contains the server mods, libraries, configuration,
default configurations, server properties, EULA file, JVM arguments,
and initial operator list.

The world is intentionally excluded. MCSync snapshots and replication
are responsible for transferring world data between peers.

ops.json is an initial copy only. Current MCSync snapshots do not
continuously synchronize operator permissions.

Each peer must configure its own MCSync local configuration and secrets.
Review Java paths and memory settings on each computer.

The EULA file currently contains eula=true. Each person running the
server must independently review and agree to the Minecraft EULA.

Excluded: worlds, backups, logs, runtime state, installer files,
machine-specific installation metadata, and launch batch scripts.
"@

    Set-Content -LiteralPath (Join-Path $StageRoot "PACK-INFO.txt") `
        -Value $Info -Encoding UTF8

    Write-Host "`nGenerating SHA-256 file manifest..."

    $Manifest = Get-ChildItem -LiteralPath $StageRoot -File -Recurse |
        ForEach-Object {
            $relativePath = $_.FullName.Substring($StageRoot.Length + 1)
            [PSCustomObject]@{
                RelativePath = $relativePath.Replace("\", "/")
                SizeBytes = $_.Length
                SHA256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            }
        } |
        Sort-Object RelativePath

    $Manifest | Export-Csv `
        -LiteralPath (Join-Path $StageRoot "PACK-MANIFEST.csv") `
        -NoTypeInformation -Encoding UTF8

    if (Test-Path $ZipPath) {
        Remove-Item $ZipPath -Force
    }

    if (Test-Path $HashPath) {
        Remove-Item $HashPath -Force
    }

    Write-Host "`nCreating ZIP archive..."
    Compress-Archive -Path (Join-Path $StageRoot "*") `
        -DestinationPath $ZipPath -CompressionLevel Optimal

    $ArchiveHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
    Set-Content -LiteralPath $HashPath `
        -Value "$ArchiveHash  $PackName.zip" -Encoding ASCII

    Write-Host "`nExport completed." -ForegroundColor Green
    Write-Host "Files in manifest: $($Manifest.Count)"
    Write-Host "Archive size:      $([math]::Round((Get-Item $ZipPath).Length / 1MB, 2)) MB"
    Write-Host "Archive:           $ZipPath"
    Write-Host "SHA-256:           $HashPath"
}
finally {
    if (Test-Path $StageRoot) {
        Remove-Item $StageRoot -Recurse -Force
    }
}
