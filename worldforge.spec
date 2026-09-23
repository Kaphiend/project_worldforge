# PyInstaller one-folder build. Run: pyinstaller --clean --noconfirm worldforge.spec
from pathlib import Path

root = Path(SPECPATH)
data_files = []
for path in (root / "data").rglob("*.json"):
    data_files.append((str(path), str(path.parent.relative_to(root))))
for path in (root / "asset_pack").glob("*.png"):
    data_files.append((str(path), "asset_pack"))

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=data_files,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Worldforge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Worldforge",
)
