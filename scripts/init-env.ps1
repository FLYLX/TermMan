param(
    [Alias("f")]
    [switch]$Force,
    [Alias("h")]
    [switch]$Help
)

$ErrorActionPreference = "Stop"

function Show-Usage {
    @"
Usage:
  powershell -ExecutionPolicy Bypass -File scripts/init-env.ps1 [-Force]

Generate .env files from every .env-example in the repository.

Rules:
  1. The repository root .env is the Docker Compose source of truth.
  2. Component .env files are generated in their own directories.
  3. Shared values that appear in both places are synced from root .env
     into component .env files so they cannot drift.

Currently synced:
  - .env VITE_API_URL -> frontend/.env VITE_API_URL
  - .env ROBOT_BRIDGE_SHARED_SECRET -> robot/.env ROBOT_BRIDGE_SHARED_SECRET
    falling back to .env SECRET_KEY when no bridge secret is set.

Options:
  -Force   Overwrite existing .env files from .env-example first.
  -Help    Show this help.
"@
}

function Get-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    $line = Get-Content -LiteralPath $Path |
        Where-Object {
            $trimmed = $_.TrimStart()
            $trimmed -and -not $trimmed.StartsWith("#") -and $trimmed.StartsWith("$Key=")
        } |
        Select-Object -Last 1

    if (-not $line) {
        return $null
    }

    return $line.Substring($line.IndexOf("=") + 1).TrimEnd("`r")
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = Get-Content -LiteralPath $Path
    $found = $false
    $updated = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Key))=") {
            $found = $true
            "$Key=$Value"
        } else {
            $line
        }
    }

    if (-not $found) {
        $updated += "$Key=$Value"
    }

    Set-Content -LiteralPath $Path -Value $updated
}

function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $prefix = "$rootPath\"

    if ($fullPath.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $fullPath.Substring($prefix.Length)
    }

    if ($fullPath.Equals($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return "."
    }

    return $fullPath
}

function Copy-EnvExample {
    param(
        [Parameter(Mandatory = $true)][string]$ExamplePath,
        [Parameter(Mandatory = $true)][string]$EnvPath
    )

    $relExample = Get-RelativePath -Root $repoRoot -Path $ExamplePath
    $relEnv = Get-RelativePath -Root $repoRoot -Path $EnvPath

    if ((Test-Path -LiteralPath $EnvPath) -and -not $Force) {
        Write-Host "skip   $relEnv already exists (from $relExample)"
        return
    }

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $EnvPath) | Out-Null
    Copy-Item -LiteralPath $ExamplePath -Destination $EnvPath -Force
    Write-Host "write  $relEnv (from $relExample)"
}

function Sync-FrontendEnv {
    $rootEnv = Join-Path $repoRoot ".env"
    $frontendEnv = Join-Path $repoRoot "frontend\.env"
    $viteApiUrl = Get-EnvValue -Path $rootEnv -Key "VITE_API_URL"

    if ((Test-Path -LiteralPath $frontendEnv) -and $viteApiUrl) {
        Set-EnvValue -Path $frontendEnv -Key "VITE_API_URL" -Value $viteApiUrl
        Write-Host "sync   frontend\.env VITE_API_URL from .env"
    }
}

function Sync-RobotEnv {
    $rootEnv = Join-Path $repoRoot ".env"
    $robotEnv = Join-Path $repoRoot "robot\.env"
    $bridgeSecret = Get-EnvValue -Path $rootEnv -Key "ROBOT_BRIDGE_SHARED_SECRET"
    $secretKey = Get-EnvValue -Path $rootEnv -Key "SECRET_KEY"

    if (-not (Test-Path -LiteralPath $robotEnv)) {
        return
    }

    if ($bridgeSecret) {
        Set-EnvValue -Path $robotEnv -Key "ROBOT_BRIDGE_SHARED_SECRET" -Value $bridgeSecret
        Write-Host "sync   robot\.env bridge token from .env ROBOT_BRIDGE_SHARED_SECRET"
    } elseif ($secretKey) {
        Set-EnvValue -Path $robotEnv -Key "ROBOT_BRIDGE_SHARED_SECRET" -Value $secretKey
        Write-Host "sync   robot\.env bridge token from .env SECRET_KEY"
    }
}

if ($Help) {
    Show-Usage
    exit 0
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).ProviderPath
$rootExample = Join-Path $repoRoot ".env-example"
$rootEnv = Join-Path $repoRoot ".env"

if (-not (Test-Path -LiteralPath $rootExample)) {
    throw "Missing root .env-example: $rootExample"
}

Copy-EnvExample -ExamplePath $rootExample -EnvPath $rootEnv

$examples = Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -File -Filter ".env-example" |
    Where-Object {
        $relative = Get-RelativePath -Root $repoRoot -Path $_.FullName
        -not ($relative -eq ".env-example" -or $relative -like ".git\*" -or $relative -like "node_modules\*")
    } |
    Sort-Object FullName

foreach ($exampleFile in $examples) {
    $envFile = Join-Path $exampleFile.DirectoryName ".env"
    Copy-EnvExample -ExamplePath $exampleFile.FullName -EnvPath $envFile
}

Sync-FrontendEnv
Sync-RobotEnv

Write-Host "Done."