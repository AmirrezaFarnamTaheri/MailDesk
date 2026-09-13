param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$PythonOnPath = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $PythonOnPath) {
    $PythonOnPath = (Get-Command python -ErrorAction Stop).Source
}

if (-not (Test-Path '.venv-build\Scripts\python.exe')) {
    & $PythonOnPath -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the build virtual environment.' }
}

$Python = Join-Path $Root '.venv-build\Scripts\python.exe'
& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $Python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed.' }
& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Installed build dependencies are inconsistent.' }

& $Python -m compileall -q mailmerge_app
if ($LASTEXITCODE -ne 0) { throw 'Python compilation check failed.' }
& $Python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }

$Version = (& $Python -c "import mailmerge_app; print(mailmerge_app.__version__)" | Select-Object -Last 1).Trim()
if (-not $Version) { throw 'Could not determine application version.' }

& $Python -m PyInstaller --noconfirm --clean packaging\MailDesk.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

$Exe = Join-Path $Root 'dist\MailDesk.exe'
if (-not (Test-Path $Exe)) { throw "PyInstaller did not produce $Exe" }

$HasSigningCertificate = -not [string]::IsNullOrWhiteSpace($env:MAILDESK_SIGN_CERT_PFX) -or -not [string]::IsNullOrWhiteSpace($env:MAILMERGE_SIGN_CERT_PFX)
$CertPfx = if (-not [string]::IsNullOrWhiteSpace($env:MAILDESK_SIGN_CERT_PFX)) { $env:MAILDESK_SIGN_CERT_PFX } else { $env:MAILMERGE_SIGN_CERT_PFX }
$CertPwd = if (-not [string]::IsNullOrWhiteSpace($env:MAILDESK_SIGN_CERT_PASSWORD)) { $env:MAILDESK_SIGN_CERT_PASSWORD } else { $env:MAILMERGE_SIGN_CERT_PASSWORD }
$HasSigningPassword = -not [string]::IsNullOrWhiteSpace($CertPwd)
if ($HasSigningCertificate -xor $HasSigningPassword) {
    throw 'Signing configuration is incomplete. Provide both MAILDESK_SIGN_CERT_PFX and MAILDESK_SIGN_CERT_PASSWORD, or neither.'
}

function Sign-Artifact([string]$Path) {
    if (-not $HasSigningCertificate) { return }
    $signtool = (Get-Command signtool.exe -ErrorAction Stop).Source
    & $signtool sign /fd SHA256 /f $CertPfx /p $CertPwd /tr https://timestamp.digicert.com /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw "Signing failed for $Path" }
}

function Stop-ProcessTree([Diagnostics.Process]$Process) {
    if ($Process.HasExited) { return }
    try {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
    catch {
        try { $Process.Kill($true) } catch { }
    }
}

function Invoke-FrozenSmokeTest([string]$Executable, [string]$Marker, [int]$TimeoutSeconds = 45) {
    Remove-Item -LiteralPath $Marker -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath $Executable -ArgumentList @('--build-smoke-test', $Marker) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    try {
        while ([DateTime]::UtcNow -lt $deadline) {
            if (Test-Path -LiteralPath $Marker) {
                # The marker is the frozen-child startup contract. A PyInstaller
                # one-file GUI parent can remain resident while bundled GUI/CLR
                # teardown completes on a headless runner, so process exit is not
                # a reliable success signal. Validate the marker, then terminate
                # the probe tree explicitly in the finally block.
                $detail = (Get-Content -LiteralPath $Marker -Raw).Trim()
                if ($detail.StartsWith('ERROR:')) {
                    throw "The packaged executable reported a startup error: $detail"
                }
                if ([string]::IsNullOrWhiteSpace($detail)) {
                    Start-Sleep -Milliseconds 100
                    continue
                }
                return
            }
            if ($process.HasExited) {
                throw "The packaged executable exited with code $($process.ExitCode) before writing its smoke-test marker."
            }
            Start-Sleep -Milliseconds 200
        }
        throw "Frozen executable did not produce its startup marker within $TimeoutSeconds seconds."
    }
    finally {
        Stop-ProcessTree $process
        $process.Dispose()
    }
}

Sign-Artifact $Exe

$SmokeMarker = Join-Path $env:TEMP "maildesk-smoke-$PID.txt"
Invoke-FrozenSmokeTest -Executable $Exe -Marker $SmokeMarker
$VersionOutput = (Get-Content -LiteralPath $SmokeMarker -Raw).Trim()
Remove-Item -LiteralPath $SmokeMarker -Force -ErrorAction SilentlyContinue
$ExpectedVersionOutput = "MailDesk $Version"
if ($VersionOutput -ne $ExpectedVersionOutput) {
    throw "Unexpected executable smoke-test marker. Expected '$ExpectedVersionOutput', got '$VersionOutput'."
}

$Artifacts = [Collections.Generic.List[string]]::new()
$Artifacts.Add($Exe)

if (-not $SkipInstaller) {
    $Inno = @(
        "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Inno) { throw 'Inno Setup 6 is required to build the installer.' }

    & $Inno "/DMyAppVersion=$Version" packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }

    $Installer = Join-Path $Root "dist\installer\MailDesk-$Version-Setup.exe"
    if (-not (Test-Path $Installer)) { throw "Installer was not produced: $Installer" }
    Sign-Artifact $Installer
    $Artifacts.Add($Installer)
}

$ChecksumPath = Join-Path $Root 'dist\SHA256SUMS.txt'
$ChecksumLines = foreach ($Artifact in $Artifacts) {
    $Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Artifact).Hash.ToLowerInvariant()
    "$Hash  $([IO.Path]::GetFileName($Artifact))"
}
[IO.File]::WriteAllLines($ChecksumPath, $ChecksumLines, [Text.UTF8Encoding]::new($false))

Write-Host "Build complete for MailDesk $Version"
foreach ($Artifact in $Artifacts) { Write-Host "Built: $Artifact" }
Write-Host "Checksums: $ChecksumPath"