$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    try { py -3.11 -m venv .venv } catch { py -3 -m venv .venv }
    & $python -m pip install --upgrade pip
    & $python -m pip install -r requirements.txt
}
& $python -m mailmerge_app.desktop
