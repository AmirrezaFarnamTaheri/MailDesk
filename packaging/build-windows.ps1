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

function Test-FrozenArtifact([string]$Executable) {
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "Frozen executable is missing: $Executable"
    }

    $info = Get-Item -LiteralPath $Executable
    if ($info.Length -lt 5MB) {
        throw "Frozen executable is unexpectedly small ($($info.Length) bytes)."
    }

    $stream = [IO.File]::OpenRead($Executable)
    try {
        $first = $stream.ReadByte()
        $second = $stream.ReadByte()
        if ($first -ne 0x4D -or $second -ne 0x5A) {
            throw 'MailDesk.exe is not a valid PE/MZ executable.'
        }
    }
    finally {
        $stream.Dispose()
    }

    # Inspect the produced one-file CArchive before executing it. This catches
    # missing hidden modules/native payloads with precise diagnostics and avoids
    # conflating archive completeness with runtime bootstrap behavior.
    $archiveViewer = Join-Path $Root '.venv-build\Scripts\pyi-archive_viewer.exe'
    if (-not (Test-Path -LiteralPath $archiveViewer)) {
        throw 'PyInstaller archive viewer is missing from the build environment.'
    }
    $archiveOutput = (& $archiveViewer -r -b $Executable 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the frozen PyInstaller archive: $archiveOutput"
    }

    # Include the build-time TOCs as a second source for hidden-module names while
    # the recursive executable listing proves that the produced EXE is itself a
    # parseable PyInstaller archive.
    $tocText = (Get-ChildItem -LiteralPath (Join-Path $Root 'build\MailDesk') -Filter '*.toc' -File -ErrorAction Stop |
        ForEach-Object { Get-Content -LiteralPath $_.FullName -Raw }) -join "`n"
    $manifest = ($archiveOutput + "`n" + $tocText).Replace('\', '/')

    $requiredEntries = @(
        'mailmerge_app.desktop',
        'mailmerge_app.main',
        'webview',
        'pythonnet',
        'clr_loader',
        'Microsoft.Web.WebView2.Core.dll',
        'Microsoft.Web.WebView2.WinForms.dll',
        'mailmerge_app/static/app.js',
        'mailmerge_app/static/index.html'
    )
    foreach ($entry in $requiredEntries) {
        if ($manifest.IndexOf($entry, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Frozen artifact is missing required runtime content: $entry"
        }
    }

    $warningPath = Join-Path $Root 'build\MailDesk\warn-MailDesk.txt'
    if (-not (Test-Path -LiteralPath $warningPath)) {
        throw 'PyInstaller warning report was not produced.'
    }
    $warnings = Get-Content -LiteralPath $warningPath -Raw
    foreach ($module in @('mailmerge_app.desktop', 'mailmerge_app.main', 'webview', 'pythonnet', 'clr_loader')) {
        $plainMissing = "missing module named $module"
        $quotedMissing = "missing module named '$module'"
        if ($warnings.IndexOf($plainMissing, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
            $warnings.IndexOf($quotedMissing, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "PyInstaller reported required module as missing: $module"
        }
    }

    Write-Host "Frozen artifact integrity verified: $($info.Length) bytes"
}

function Stop-ProcessTree([Diagnostics.Process]$Process) {
    try {
        if ($Process.HasExited) { return }
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
    catch {
        try { $Process.Kill($true) } catch { }
    }
}

function Invoke-FrozenBootstrapSmoke([string]$Executable, [string]$ExpectedVersion, [int]$TimeoutSeconds = 90) {
    # Use a relative marker argument so the command line stays safe even when the
    # checkout path contains spaces. build-windows.ps1 already sets cwd to $Root.
    $markerRelative = "dist\maildesk-bootstrap-smoke-$PID.txt"
    $marker = Join-Path $Root $markerRelative
    Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue

    $process = Start-Process -FilePath $Executable -ArgumentList @('--build-smoke-test', $markerRelative) -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    try {
        while ([DateTime]::UtcNow -lt $deadline) {
            if (Test-Path -LiteralPath $marker) {
                $detail = (Get-Content -LiteralPath $marker -Raw).Trim()
                if ([string]::IsNullOrWhiteSpace($detail)) {
                    Start-Sleep -Milliseconds 100
                    continue
                }
                if ($detail.StartsWith('ERROR:')) {
                    throw "Frozen executable bootstrap reported an error: $detail"
                }
                $expected = "MailDesk $ExpectedVersion"
                if ($detail -ne $expected) {
                    throw "Unexpected frozen bootstrap marker. Expected '$expected', got '$detail'."
                }
                Write-Host "Frozen executable bootstrap verified: $detail"
                return
            }

            if ($process.HasExited) {
                throw "Frozen executable exited with code $($process.ExitCode) before completing its bootstrap smoke test."
            }
            Start-Sleep -Milliseconds 200
        }
        throw "Frozen executable did not complete its bootstrap smoke test within $TimeoutSeconds seconds."
    }
    finally {
        Stop-ProcessTree $process
        $process.Dispose()
        Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-InnoCompiler {
    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -and (Test-Path -LiteralPath $command.Source)) {
        return $command.Source
    }

    # Environment-variable names containing parentheses cannot be expanded safely
    # as "$env:ProgramFiles(x86)"; that form is parsed as ProgramFiles plus literal
    # text and produces a malformed path. Resolve the variables explicitly.
    $roots = @(
        [Environment]::GetEnvironmentVariable('ProgramFiles(x86)'),
        [Environment]::GetEnvironmentVariable('ProgramFiles')
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($rootPath in $roots) {
        $candidate = Join-Path $rootPath 'Inno Setup 6\ISCC.exe'
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:ChocolateyInstall)) {
        $shim = Join-Path $env:ChocolateyInstall 'bin\ISCC.exe'
        if (Test-Path -LiteralPath $shim) {
            return $shim
        }
    }
    return $null
}

Test-FrozenArtifact $Exe
Invoke-FrozenBootstrapSmoke -Executable $Exe -ExpectedVersion $Version
Sign-Artifact $Exe

$Artifacts = [Collections.Generic.List[string]]::new()
$Artifacts.Add($Exe)

if (-not $SkipInstaller) {
    $Inno = Resolve-InnoCompiler
    if (-not $Inno) { throw 'Inno Setup 6 is required to build the installer.' }

    Write-Host "Using Inno Setup compiler: $Inno"
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