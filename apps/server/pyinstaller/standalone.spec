# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SERVER_ROOT = Path(SPECPATH).resolve().parent
ALEMBIC_ROOT = SERVER_ROOT / "alembic"
ONEFILE = False

alembic_datas = [
    (str(SERVER_ROOT / "alembic.ini"), "alembic"),
    (str(ALEMBIC_ROOT / "env.py"), "alembic"),
    (str(ALEMBIC_ROOT / "script.py.mako"), "alembic"),
]
alembic_datas.extend(
    (str(path), "alembic/versions")
    for path in sorted((ALEMBIC_ROOT / "versions").glob("*.py"))
)

# Alembic migration scripts are deliberately bundled as filesystem data because
# ScriptDirectory executes them by path. app.standalone is a true hidden import
# because uvicorn loads it from the string "app.standalone:app".
hiddenimports = [
    "app.standalone",
    *collect_submodules("alembic"),
    *collect_submodules("pydantic"),
    *collect_submodules("pydantic_core"),
]

analysis = Analysis(
    [str(SERVER_ROOT / "app" / "launcher.py")],
    pathex=[str(SERVER_ROOT)],
    binaries=[],
    datas=alembic_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["psycopg", "psycopg_binary", "psycopg_c"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="adventure-table",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="adventure-table-standalone",
)
