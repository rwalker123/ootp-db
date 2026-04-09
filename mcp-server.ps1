#Requires -Version 5.1
# OOTP MCP server (stdio). Cursor normally launches this automatically; use this script
# to verify the venv, deps, or run with MCP Inspector. Blocks waiting for JSON-RPC on stdin.
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "X Python not found. Install it from https://python.org"
    exit 1
}

if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "X Failed to create virtual environment."
        exit 1
    }
}

& ".venv\Scripts\pip" install -q -r requirements.txt

Write-Host "Checking for updates..."
if (Test-Path ".git") {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        '{"updates_available": null, "install_type": "git"}' | Set-Content .update-status -Encoding UTF8
        Write-Host "! Unable to check for updates (git not found on PATH)"
    } else {
        git fetch origin --quiet 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $behind = [int](git rev-list HEAD..origin/main --count 2>$null)
            if ($behind -gt 0) {
                '{"updates_available": true, "install_type": "git"}' | Set-Content .update-status -Encoding UTF8
                Write-Host "! Update available -- run: git pull"
            } else {
                '{"updates_available": false, "install_type": "git"}' | Set-Content .update-status -Encoding UTF8
                Write-Host "OK Up to date"
            }
        } else {
            '{"updates_available": null, "install_type": "git"}' | Set-Content .update-status -Encoding UTF8
            Write-Host "! Unable to check for updates"
        }
    }
} else {
    if (-not (Test-Path ".downloaded")) {
        (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") | Set-Content .downloaded
    }
    $downloaded = (Get-Content .downloaded).Trim()
    try {
        $apiResponse = Invoke-WebRequest -Uri "https://api.github.com/repos/rwalker123/ootp-db/commits/main" `
            -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $latest = ($apiResponse.Content | ConvertFrom-Json).commit.committer.date
        if ($latest -gt $downloaded) {
            '{"updates_available": true, "install_type": "zip"}' | Set-Content .update-status -Encoding UTF8
            Write-Host "! Update available -- download: https://github.com/rwalker123/ootp-db/archive/refs/heads/main.zip"
        } else {
            '{"updates_available": false, "install_type": "zip"}' | Set-Content .update-status -Encoding UTF8
            Write-Host "OK Up to date"
        }
    } catch {
        '{"updates_available": null, "install_type": "zip"}' | Set-Content .update-status -Encoding UTF8
        Write-Host "! Unable to check for updates"
    }
}

Write-Host ""
Write-Host "Starting OOTP MCP server (stdio) -- waiting for a client on stdin."
Write-Host "Tip: Cursor starts this automatically when MCP is configured; use this for testing or MCP Inspector."
Write-Host ""

& (Resolve-Path ".venv\Scripts\python.exe").Path "mcp_server.py"
