param(
    [ValidateSet("build", "start", "stop", "status", "logs", "validate-config")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$EnvironmentFile = Join-Path $WorkspaceRoot ".env.worker"
$ComposeFile = Join-Path $WorkspaceRoot "compose.worker.yaml"

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Missing .env.worker. Copy .env.worker.example and fill private VPN endpoints and worker credentials."
}

$Transport = "vpn"
foreach ($Line in Get-Content -LiteralPath $EnvironmentFile) {
    if ($Line -match '^WORKER_TRANSPORT=(.+)$') {
        $Transport = $Matches[1].Trim().ToLowerInvariant()
    }
}

$ComposeArguments = @("compose", "--env-file", $EnvironmentFile, "-f", $ComposeFile)
if ($Transport -eq "ssh") {
    $ComposeArguments += @("-f", (Join-Path $WorkspaceRoot "compose.worker.ssh.yaml"))
} elseif ($Transport -ne "vpn") {
    throw "Unsupported WORKER_TRANSPORT '$Transport'. Use 'ssh' or 'vpn'."
}

switch ($Action) {
    "validate-config" {
        & docker @ComposeArguments config --quiet
    }
    "build" {
        & docker @ComposeArguments build --pull compute-worker
    }
    "start" {
        & docker @ComposeArguments up -d compute-worker
    }
    "stop" {
        & docker @ComposeArguments stop -t 120 compute-worker
    }
    "status" {
        & docker @ComposeArguments ps
    }
    "logs" {
        & docker @ComposeArguments logs --tail 200 -f compute-worker
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "Compute worker action '$Action' failed with exit code $LASTEXITCODE."
}
