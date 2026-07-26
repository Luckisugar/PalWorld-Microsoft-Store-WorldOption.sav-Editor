# Palworld MS Toolkit launcher - works with ZERO Python installed.
# ASCII-only so PowerShell on any Windows code page can parse it.

# Do NOT use Stop globally - native python/pip stderr would crash the launcher
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

try {
    $Host.UI.RawUI.WindowTitle = "Palworld MS Toolkit - Launcher"
} catch {}

Write-Host ""
Write-Host "  Palworld MS Store Toolkit - Launcher" -ForegroundColor Cyan
Write-Host "  =====================================" -ForegroundColor DarkCyan
Write-Host ""

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$PyArgs,
        [switch]$ShowOutput
    )
    # Run via cmd so PowerShell never treats Python stderr as a terminating error
    $argLine = ($PyArgs | ForEach-Object {
        if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ }
    }) -join " "
    $cmd = "`"$Exe`" $argLine"
    $out = & cmd.exe /c $cmd 2>&1
    $code = $LASTEXITCODE
    $text = ($out | Out-String)
    if ($ShowOutput -and $text.Trim()) {
        Write-Host $text
    }
    return @{ Code = $code; Text = $text }
}

function Test-PythonOk {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    $r = Invoke-Python -Exe $Exe -PyArgs @("-c", "import sys; print('%d.%d' % (sys.version_info[0], sys.version_info[1]))")
    if ($r.Code -ne 0) { return $false }
    $v = ($r.Text).Trim()
    if (-not $v) { return $false }
    $parts = $v.Split(".")
    try {
        $major = [int]$parts[0]
        $minor = [int]$parts[1]
    } catch { return $false }
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) { return $false }
    $t = Invoke-Python -Exe $Exe -PyArgs @("-c", "import tkinter")
    return ($t.Code -eq 0)
}

function Find-Python {
    $candidates = New-Object System.Collections.Generic.List[string]

    foreach ($name in @("python", "python3")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -and ($cmd.Source -notmatch 'WindowsApps\\python')) {
            [void]$candidates.Add([string]$cmd.Source)
        }
    }

    # py launcher
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        foreach ($flag in @("-3.12", "-3.13", "-3.11", "-3.10", "-3")) {
            $r = & cmd.exe /c "py $flag -c `"import sys; print(sys.executable)`"" 2>&1
            if ($LASTEXITCODE -eq 0 -and $r) {
                $line = ($r | Select-Object -Last 1).ToString().Trim()
                if ($line -and (Test-Path -LiteralPath $line)) {
                    [void]$candidates.Add($line)
                }
            }
        }
    }

    $local = $env:LOCALAPPDATA
    $pf = $env:ProgramFiles
    foreach ($p in @(
        "$local\Programs\Python\Python312\python.exe",
        "$local\Programs\Python\Python313\python.exe",
        "$local\Programs\Python\Python311\python.exe",
        "$local\Programs\Python\Python310\python.exe",
        "$pf\Python312\python.exe",
        "$pf\Python313\python.exe"
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
        Write-Host "  Download failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "  Open https://www.python.org/downloads/ manually, install, check Add python.exe to PATH." -ForegroundColor Yellow
        return $null
    }

    Write-Host "  Running installer (current user, pip + tcl/tk, add to PATH)..." -ForegroundColor Cyan
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

    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")

    Start-Sleep -Seconds 2
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

function Test-Import {
    param([string]$Python, [string]$Module)
    $r = Invoke-Python -Exe $Python -PyArgs @("-c", "import $Module")
    return ($r.Code -eq 0)
}

function Install-PipPackage {
    param(
        [string]$Python,
        [string]$Package
    )
    Write-Host "  Installing $Package ..." -ForegroundColor Cyan
    $r = Invoke-Python -Exe $Python -PyArgs @("-m", "pip", "install", "--upgrade", $Package) -ShowOutput
    if ($r.Code -ne 0) {
        Write-Host "  pip failed for $Package (exit $($r.Code))" -ForegroundColor Red
        if ($r.Text.Trim()) {
            Write-Host $r.Text -ForegroundColor DarkYellow
        }
        return $false
    }
    return $true
}

function Ensure-Deps {
    param([string]$Python)
    Write-Host "  Checking packages..." -ForegroundColor Cyan

    # Make sure pip exists (fresh installs sometimes need ensurepip)
    $pipCheck = Invoke-Python -Exe $Python -PyArgs @("-m", "pip", "--version")
    if ($pipCheck.Code -ne 0) {
        Write-Host "  Bootstrapping pip (ensurepip)..." -ForegroundColor Cyan
        $ep = Invoke-Python -Exe $Python -PyArgs @("-m", "ensurepip", "--upgrade") -ShowOutput
        if ($ep.Code -ne 0) {
            throw "Could not install pip. Reinstall Python and tick 'pip'."
        }
        Invoke-Python -Exe $Python -PyArgs @("-m", "pip", "install", "--upgrade", "pip") | Out-Null
    }

    if (-not (Test-Import -Python $Python -Module "customtkinter")) {
        if (-not (Install-PipPackage -Python $Python -Package "customtkinter")) {
            throw "Failed to install customtkinter. Check internet / antivirus."
        }
        if (-not (Test-Import -Python $Python -Module "customtkinter")) {
            throw "customtkinter installed but still cannot import. Try: python -m pip install customtkinter"
        }
    } else {
        Write-Host "  customtkinter OK" -ForegroundColor DarkGray
    }

    if (-not (Test-Import -Python $Python -Module "palworld_save_tools")) {
        if (-not (Install-PipPackage -Python $Python -Package "palworld-save-tools")) {
            throw "Failed to install palworld-save-tools. Check internet / antivirus."
        }
        if (-not (Test-Import -Python $Python -Module "palworld_save_tools")) {
            throw "palworld_save_tools installed but still cannot import."
        }
    } else {
        Write-Host "  palworld_save_tools OK" -ForegroundColor DarkGray
    }

    Write-Host "  Packages OK." -ForegroundColor Green
}

function Show-Pause {
    Write-Host ""
    Write-Host "  Press any key to exit..."
    try {
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    } catch {
        Read-Host "  Press Enter to exit"
    }
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
        Show-Pause
        exit 1
    }

    Ensure-Deps -Python $python

    Write-Host ""
    Write-Host "  Starting app..." -ForegroundColor Cyan
    Write-Host ""
    $app = Join-Path $Root "app.py"
    if (-not (Test-Path -LiteralPath $app)) {
        throw "app.py not found next to run.bat: $app"
    }
    $run = Invoke-Python -Exe $python -PyArgs @($app) -ShowOutput
    if ($run.Code -ne 0) {
        Write-Host ""
        Write-Host "  App exited with code $($run.Code)" -ForegroundColor Red
        if ($run.Text.Trim()) {
            Write-Host $run.Text -ForegroundColor DarkYellow
        }
        Show-Pause
        exit $run.Code
    }
} catch {
    Write-Host ""
    Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ScriptStackTrace) {
        Write-Host "  $($_.ScriptStackTrace)" -ForegroundColor DarkGray
    }
    if ($_.Exception.InnerException) {
        Write-Host "  Inner: $($_.Exception.InnerException.Message)" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  Tip: open a terminal in this folder and run:" -ForegroundColor Yellow
    Write-Host "    python -m pip install customtkinter palworld-save-tools" -ForegroundColor White
    Write-Host "    python app.py" -ForegroundColor White
    Show-Pause
    exit 1
}
