# PyInstaller spec for the Windows desktop build.
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / 'mailmerge_app' / 'desktop.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'mailmerge_app' / 'static'), 'mailmerge_app/static')],
    hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MailDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / 'assets' / 'mailmerge.ico'),
)
