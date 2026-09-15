# -*- mode: python ; coding: utf-8 -*-
#
# Build settings chosen to minimise antivirus false positives on an unsigned
# binary. None of this substitutes for Authenticode signing, but each item
# removes a signal that reputation and heuristic scanners weigh:
#
#   upx=False    UPX packing is heavily associated with malware hiding its
#                payload, and is one of the most common causes of a false
#                positive on a PyInstaller executable.
#   version      An executable with no CompanyName/ProductName/description
#                looks anonymous; practically all legitimate software ships a
#                version resource.
#   icon         Iconless executables are treated with more suspicion.
#   console=False The detector now shows a progress window. A console flashing
#                up is alarming right after a SmartScreen warning, and is the
#                first impression most people get of the tool.
#
# The packaged build starts at entrypoint.py, which replaces RAM/disk probes
# with fail-closed versions before detector.launch() runs. The detector therefore
# never ships plausible fallback hardware values when a Windows API call fails.

a = Analysis(
    ['apps/detector/entrypoint.py'],
    pathex=['apps/detector'],
    binaries=[],
    datas=[],
    hiddenimports=['detector', 'gui', 'cpu_win'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Every megabyte is one a visitor waits for twice: once downloading, and
    # again while Chrome uploads the file for scanning, which it does for any
    # executable it has not seen signed before. None of these are imported by
    # the detector, which uses urllib, json, ctypes, subprocess and tkinter.
    #
    # Deliberately NOT excluded, though they look unused: email and http, which
    # urllib.request builds its requests from, and unicodedata, which
    # encodings.idna needs to resolve a hostname.
    excludes=[
        'unittest',
        'doctest',
        'pdb',
        'pydoc',
        'pydoc_data',
        'lib2to3',
        'distutils',
        'setuptools',
        'pip',
        'sqlite3',
        'asyncio',
        'multiprocessing',
        'concurrent',
        'curses',
        'xmlrpc',
        'pickletools',
        'tkinter.test',
        'test',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='canmypcrunai-detector',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='apps/detector/assets/icon.ico',
    version='apps/detector/version-info.txt',
)
