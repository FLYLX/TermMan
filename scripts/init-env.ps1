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

Generate .env files from every .env-example file in this repository.
When robot/.env is first generated, its bridge token is copied from the
root .env ROBOT_BRIDGE_SHARED_SECRET, or SECRET_KEY if no bridge token exists.

Options:
  -Force   Overwrite existing .env files.
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

    $prefix = "$Key="
    $line = Get-Content -LiteralPath $Path |
        Where-Object {
            $trimmed = $_.TrimStart()
            $trimmed -and -not $trimmed.StartsWith("#") -and $trimmed.StartsWith($prefix)
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

if ($Help) {
    Show-Usage
    exit 0
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $scriptDir "..")).ProviderPath
$robotEnvTouched = $false

$examples = Get-ChildItem -LiteralPath $repoRoot -Recurse -Force -File -Filter ".env-example" |
    Where-Object {
        $relative = Get-RelativePath -Root $repoRoot -Path $_.FullName
        -not ($relative -like ".git\*" -or $relative -like "node_modules\*")
    } |
    Sort-Object FullName

foreach ($exampleFile in $examples) {
    $envFile = Join-Path $exampleFile.DirectoryName ".env"
    $relExample = Get-RelativePath -Root $repoRoot -Path $exampleFile.FullName
    $relEnv = Get-RelativePath -Root $repoRoot -Path $envFile

    if ((Test-Path -LiteralPath $envFile) -and -not $Force) {
        Write-Host "skip   $relEnv already exists (from $relExample)"
        continue
    }

    Copy-Item -LiteralPath $exampleFile.FullName -Destination $envFile -Force
    Write-Host "write  $relEnv (from $relExample)"

    if ($relEnv -eq "robot\.env") {
        $robotEnvTouched = $true
    }
}

if ($robotEnvTouched) {
    $rootEnv = Join-Path $repoRoot ".env"
    $robotEnv = Join-Path $repoRoot "robot\.env"
    $bridgeSecret = Get-EnvValue -Path $rootEnv -Key "ROBOT_BRIDGE_SHARED_SECRET"
    $secretKey = Get-EnvValue -Path $rootEnv -Key "SECRET_KEY"

    if ($bridgeSecret) {
        Set-EnvValue -Path $robotEnv -Key "ROBOT_BRIDGE_SHARED_SECRET" -Value $bridgeSecret
        Write-Host "sync   robot\.env bridge token from .env ROBOT_BRIDGE_SHARED_SECRET"
    } elseif ($secretKey) {
        Set-EnvValue -Path $robotEnv -Key "ROBOT_BRIDGE_SHARED_SECRET" -Value $secretKey
        Write-Host "sync   robot\.env bridge token from .env SECRET_KEY"
    }
}

Write-Host "Done."
