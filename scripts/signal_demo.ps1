param(
    [string]$InputPath = "./runtime/features.jsonl",
    [string]$ConfigPath = "./config/defaults.yaml",
    [string]$OutputDir = "./runtime",
    [string]$Sink = "jsonl",
    [switch]$Print
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$resolvedInput = Resolve-Path -Path (Join-Path $projectRoot $InputPath) -ErrorAction Ignore
if (-not $resolvedInput) {
    $resolvedInput = Join-Path $projectRoot $InputPath
}
$resolvedConfig = Join-Path $projectRoot $ConfigPath
$resolvedOutput = Join-Path $projectRoot $OutputDir

$arguments = @(
    "-m", "mcp.signal_server.app",
    "--config", $resolvedConfig,
    "--input", $resolvedInput,
    "--sink", $Sink,
    "--out", $resolvedOutput
)
if ($Print.IsPresent) {
    $arguments += "--print"
}

python @arguments
