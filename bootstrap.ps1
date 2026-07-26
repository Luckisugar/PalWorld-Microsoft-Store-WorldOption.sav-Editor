# Palworld MS Toolkit launcher - works with ZERO Python installed.
# ASCII-only file so PowerShell on any Windows code page can parse it.
# Checks for Python, offers official install, installs deps, starts the app.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

try {
    $Host.UI.RawUI.WindowTitle = "Palworld MS Toolkit - Launcher"
} catch {}

Write-Host ""
Write-Host "  Palworld MS Store Toolkit - Launcher" -ForegroundColor Cyan
Write-Host "  =====================================" -ForegroundColor DarkCyan
Write-Host ""

function Test-PythonOk {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    try {
        $v = & $Exe -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>$null
        if (-not $v) { return $false }
        # Need 3.10+ with tkinter
        $parts = $v.Trim().Split(".")
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) { return $false }
        & $Exe -c "import tkinter" 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { return $false }
        return $true
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]

    # PATH
    foreach ($name in @("python", "python3", "py")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { [void]$candidates.Add([string]$cmd.Source) }
    }

    # py launcher specific
    try {
        $py = & py -3 -c "import sys; print(sys.executable)" 2>$null
        if ($py) { [void]$candidates.Add($py.Trim()) }
    } catch {}
    try {
        $py = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($py) { [void]$candidates.Add($py.Trim()) }
    } catch {}

    # Common install locations
    $local = $env:LOCALAPPDATA
    $pf = $env:ProgramFiles
    foreach ($p in @(
        "$local\Programs\Python\Python312\python.exe",
        "$local\Programs\Python\Python313\python.exe",
        "$local\Programs\Python\Python311\python.exe",
        "$local\Programs\Python\Python310\python.exe",
        "$pf\Python312\python.exe",
        "$pf\Python313\python.exe",
        "$local\PalworldMSTool\runtime\python-full\python.exe"
    )) {
        [void]$candidates.Add($p)
    }

    $seen = @{}
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        $key = $c.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (Test-PythonOk $c) { return $c }
    }
    return $null
}

function Install-OfficialPython {
    $ver = "3.12.8"
    $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
    $destDir = Join-Path $env:LOCALAPPDATA "PalworldMSTool\runtime"
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    $installer = Join-Path $destDir "python-$ver-amd64.exe"

    Write-Host ""
    Write-Host "  Python was not found (or has no tkinter)." -ForegroundColor Yellow
    Write-Host "  This tool needs official Python 3.10+ from python.org." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Install folder (default):" -ForegroundColor Gray
    Write-Host "    $env:LOCALAPPDATA\Programs\Python\Python312\" -ForegroundColor White
    Write-Host ""
    $ans = Read-Host "  Download and install Python $ver now? [Y/n]"
    if ($ans -match '^[nN]') {
        Write-Host "  Cancelled. Install Python from https://www.python.org/downloads/ and re-run." -ForegroundColor Red
        return $null
    }

    Write-Host "  Downloading official Python $ver ..." -ForegroundColor Cyan
    Write-Host "  $url" -ForegroundColor DarkGray
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing
    } catch {
        Write-Host "  Download failed: $_" -ForegroundColor Red
        Write-Host "  Open https://www.python.org/downloads/ manually, install, check 'Add to PATH'." -ForegroundColor Yellow
        return $null
    }

    Write-Host "  Running installer (current user, with pip + tcl/tk, add to PATH)..." -ForegroundColor Cyan
    # Official silent flags: https://docs.python.org/3/using/windows.html
    # NOTE: do not name this $args - reserved in PowerShell
    $installArgs = @(
        "/passive",
        "InstallAllUsers=0",
        "PrependPath=1",
        "Include_pip=1",
        "Include_tcltk=1",
        "Include_launcher=1",
        "Include_test=0",
        "SimpleInstall=1"
    )
    $p = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
    if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
        Write-Host "  Installer exit code: $($p.ExitCode)" -ForegroundColor Yellow
    }

    # Refresh PATH from machine+user for this process
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    $py = Find-Python
    if (-not $py) {
        $guess = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
        if (Test-PythonOk $guess) { $py = $guess }
    }
    if (-not $py) {
        Write-Host "  Python installed but not found on PATH yet." -ForegroundColor Yellow
        Write-Host "  Close this window, open a NEW terminal, run run.bat again." -ForegroundColor Yellow
        return $null
    }
    Write-Host "  Python ready: $py" -ForegroundColor Green
    return $py
}

function Ensure-Deps {
    param([string]$Python)
    Write-Host "  Checking packages..." -ForegroundColor Cyan
    & $Python -c "import customtkinter" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Installing customtkinter..." -ForegroundColor Cyan
        & $Python -m pip install --upgrade pip --quiet
        & $Python -m pip install customtkinter --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip install customtkinter failed" }
    }
    & $Python -c "import palworld_save_tools" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Installing palworld-save-tools..." -ForegroundColor Cyan
        & $Python -m pip install palworld-save-tools --quiet
        if ($LASTEXITCODE -ne 0) { throw "pip install palworld-save-tools failed" }
    }
    Write-Host "  Packages OK." -ForegroundColor Green
}

# --- main ---
try {
    $python = Find-Python
    if (-not $python) {
        $python = Install-OfficialPython
    } else {
        Write-Host "  Found Python: $python" -ForegroundColor Green
    }

    if (-not $python) {
        Write-Host ""
        Write-Host "  Press any key to exit..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        exit 1
    }

    Ensure-Deps -Python $python

    Write-Host ""
    Write-Host "  Starting app..." -ForegroundColor Cyan
    Write-Host ""
    & $python (Join-Path $Root "app.py")
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Host ""
        Write-Host "  App exited with code $code" -ForegroundColor Red
        Write-Host "  Press any key to exit..."
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
        exit $code
    }
} catch {
    Write-Host ""
    Write-Host "  ERROR: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Press any key to exit..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
