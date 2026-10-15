# PyInstaller build file: two programs sharing one folder.
#   dist\ConvenienceStorePOS\ConvenienceStorePOS.exe   the POS (no console window)
#   dist\ConvenienceStorePOS\POS Tools.exe       setup / backup / restore menu (console)
# Build with:  build_exe.bat
from PyInstaller.utils.hooks import collect_submodules

datas = [("migrations/versions/*.sql", "migrations/versions"),
         ("resources/icons/*", "resources/icons")]
hidden = collect_submodules("mysql.connector") + collect_submodules("bcrypt")
excludes = ["tkinter", "pytest", "_pytest"]

pos_a = Analysis(["main.py"], datas=datas, hiddenimports=hidden, excludes=excludes)
tools_a = Analysis(["pos_tools.py"], datas=datas,
                   hiddenimports=hidden + ["scripts.check_environment", "scripts.create_app_user",
                                           "scripts.setup_database", "scripts.restore_backup"],
                   excludes=excludes + ["PySide6"])

pos_exe = EXE(PYZ(pos_a.pure), pos_a.scripts, [], exclude_binaries=True, name="ConvenienceStorePOS",
              console=False, upx=False)
tools_exe = EXE(PYZ(tools_a.pure), tools_a.scripts, [], exclude_binaries=True, name="POS Tools",
                console=True, upx=False)

# Both programs need some of the same files; copy each one only once (a second copy of a
# read-only DLL such as ucrtbase.dll fails with "Permission denied").
have = {entry[0].lower() for entry in pos_a.binaries + pos_a.datas}
tools_binaries = [b for b in tools_a.binaries if b[0].lower() not in have]
tools_datas = [d for d in tools_a.datas if d[0].lower() not in have]

coll = COLLECT(pos_exe, pos_a.binaries, pos_a.datas,
               tools_exe, tools_binaries, tools_datas,
               name="ConvenienceStorePOS", upx=False)
