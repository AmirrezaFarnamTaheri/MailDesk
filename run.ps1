$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$VenvDir = Join-Path $PSScriptRoot '.venv'
$Python = Join-Path $VenvDir 'Scripts\python.exe'

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

function New-MailDeskVenv {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        foreach ($version in @('3.13', '3.12', '3.11')) {
            & $py.Source "-$version" -m venv $VenvDir 2>$null
            if ($LASTEXITCODE -eq 0 -and (Test-Path $Python)) { return }
        }
    }

    $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $systemPython) { $systemPython = Get-Command python -ErrorAction SilentlyContinue }
    if ($systemPython) {
        & $systemPython.Source -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
        if ($LASTEXITCODE -eq 0) {
            Invoke-NativeChecked -FilePath $systemPython.Source -Arguments @('-m', 'venv', $VenvDir)
            return
        }
    }
    throw 'Python 3.11 or later is required. Install Python and try again.'
}

if (-not (Test-Path $Python)) {
    New-MailDeskVenv
}

# Reject an old/stale environment explicitly instead of failing later inside a
# dependency with a confusing syntax/import error.
& $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw 'The existing .venv uses Python older than 3.11. Delete .venv and run MailDesk again.'
}

# Reinstall only when requirements.txt changes. This keeps source launches fast
# while ensuring an existing environment does not silently drift behind the repo.
$Requirements = Join-Path $PSScriptRoot 'requirements.txt'
$RequirementHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Requirements).Hash.ToLowerInvariant()
$HashMarker = Join-Path $VenvDir 'maildesk-requirements.sha256'
$InstalledHash = if (Test-Path $HashMarker) { (Get-Content -LiteralPath $HashMarker -Raw).Trim() } else { '' }
if ($InstalledHash -ne $RequirementHash) {
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    Invoke-NativeChecked -FilePath $Python -Arguments @('-m', 'pip', 'install', '-r', $Requirements)
    [IO.File]::WriteAllText($HashMarker, $RequirementHash, [Text.UTF8Encoding]::new($false))
}

& $Python -m mailmerge_app.desktop
exit $LASTEXITCODE
