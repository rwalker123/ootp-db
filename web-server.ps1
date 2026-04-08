#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

# ---------------------------------------------------------------------------
# Check Python
# ---------------------------------------------------------------------------
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "X Python not found. Install it from https://python.org"
    exit 1
}

# ---------------------------------------------------------------------------
# Create venv if missing
# ---------------------------------------------------------------------------
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "X Failed to create virtual environment."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Install/update packages
# ---------------------------------------------------------------------------
& ".venv\Scripts\pip" install -q -r requirements.txt

# ---------------------------------------------------------------------------
# Check for updates
# ---------------------------------------------------------------------------
Write-Host "Checking for updates..."
if (Test-Path ".git") {
    git fetch origin --quiet 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $behind = [int](git rev-list HEAD..origin/main --count 2>$null)
        if ($behind -gt 0) {
            '{"updates_available": true, "install_type": "git"}' | Set-Content .update-status
            Write-Host "! Update available -- run: git pull"
        } else {
            '{"updates_available": false, "install_type": "git"}' | Set-Content .update-status
            Write-Host "OK Up to date"
        }
    } else {
        '{"updates_available": null, "install_type": "git"}' | Set-Content .update-status
        Write-Host "! Unable to check for updates"
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
            '{"updates_available": true, "install_type": "zip"}' | Set-Content .update-status
            Write-Host "! Update available -- download: https://github.com/rwalker123/ootp-db/archive/refs/heads/main.zip"
        } else {
            '{"updates_available": false, "install_type": "zip"}' | Set-Content .update-status
            Write-Host "OK Up to date"
        }
    } catch {
        '{"updates_available": null, "install_type": "zip"}' | Set-Content .update-status
        Write-Host "! Unable to check for updates"
    }
}

# ---------------------------------------------------------------------------
# Check if a server is already running on port 8000
# ---------------------------------------------------------------------------
$serverRunning = $false
try {
    $null = Invoke-WebRequest -Uri "http://localhost:8000/status" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
    $serverRunning = $true
} catch {}

if ($serverRunning) {
    $existingPid = $null
    $netConn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($netConn) { $existingPid = $netConn.OwningProcess }
    $pidStr = if ($existingPid) { $existingPid } else { "unknown" }
    Write-Host "! A server is already running on port 8000 (PID $pidStr)."
    $choice = Read-Host "  [k] Kill it and start fresh  [u] Use it (open browser)  [q] Quit"
    switch ($choice.ToLower()) {
        'k' {
            if ($existingPid) {
                Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
                Write-Host "OK Killed existing server (PID $existingPid)"
            }
        }
        'u' {
            Start-Process "http://localhost:8000"
            exit 0
        }
        default {
            Write-Host "Quit."
            exit 0
        }
    }
}

# ---------------------------------------------------------------------------
# Start server
# ---------------------------------------------------------------------------
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = (Resolve-Path ".venv\Scripts\python.exe").Path
$psi.Arguments = "server.py"
$psi.WorkingDirectory = $PSScriptRoot
$psi.UseShellExecute = $false
$serverProcess = [System.Diagnostics.Process]::Start($psi)
Write-Host "Starting server (PID $($serverProcess.Id))..."

# Wait for server to be ready (up to 10s)
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        Write-Host "X Server exited unexpectedly. Check for errors above."
        exit 1
    }
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:8000/status" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
        $ready = $true
        break
    } catch {}
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Write-Host "X Server did not become ready after 10s. Check for errors above."
    Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Start-Process "http://localhost:8000"

# ---------------------------------------------------------------------------
# Interactive command loop
# ---------------------------------------------------------------------------
Write-Host "Server running. Commands: [r] restart  [q] quit"
while ($true) {
    $cmd = Read-Host ">"
    switch ($cmd.ToLower()) {
        'r' {
            Write-Host "Restarting server (killing PID $($serverProcess.Id))..."
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
            $serverProcess.WaitForExit(3000) | Out-Null

            $psi2 = New-Object System.Diagnostics.ProcessStartInfo
            $psi2.FileName = (Resolve-Path ".venv\Scripts\python.exe").Path
            $psi2.Arguments = "server.py"
            $psi2.WorkingDirectory = $PSScriptRoot
            $psi2.UseShellExecute = $false
            $serverProcess = [System.Diagnostics.Process]::Start($psi2)
            Write-Host "Starting server (PID $($serverProcess.Id))..."

            $ready = $false
            for ($i = 0; $i -lt 20; $i++) {
                $serverProcess.Refresh()
                if ($serverProcess.HasExited) {
                    Write-Host "X Server exited unexpectedly. Check for errors above."
                    break
                }
                try {
                    $null = Invoke-WebRequest -Uri "http://localhost:8000/status" -TimeoutSec 1 -UseBasicParsing -ErrorAction Stop
                    $ready = $true
                    break
                } catch {}
                Start-Sleep -Milliseconds 500
            }
            if ($ready) {
                Write-Host "OK Server restarted (PID $($serverProcess.Id))"
            } else {
                Write-Host "X Server did not become ready. Commands: [r] restart  [q] quit"
            }
        }
        { $_ -in @('q', '') } {
            Write-Host "Stopping server (PID $($serverProcess.Id))..."
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
            $serverProcess.WaitForExit(3000) | Out-Null
            Write-Host "OK Server stopped."
            exit 0
        }
        default {
            Write-Host "Commands: [r] restart  [q] quit"
        }
    }
}
