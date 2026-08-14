# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = []
hiddenimports = ['aksal.dualctc', 'aksal.hfmodel', 'aksal.catalog', 'aksal.fetch', 'aksal.discover', 'aksal.tools', 'scipy.special.cython_special']
datas += collect_data_files('unidic_lite')
datas += collect_data_files('ipadic')
hiddenimports += collect_submodules('transformers.models.wav2vec2')


a = Analysis(
    ['E:/anime + fansubs/Duel masters/21-Duel Masters LOST/unext raws/Amazon/s3/aksal/packaging/entry.py'],
    pathex=['E:/anime + fansubs/Duel masters/21-Duel Masters LOST/unext raws/Amazon/s3/aksal/src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow', 'flax', 'jax', 'jaxlib', 'keras', 'torchvision', 'matplotlib', 'pandas', 'IPython', 'notebook', 'jupyter', 'pytest', '_pytest', 'tkinter', 'demucs', 'julius', 'openunmix', 'yt_dlp', 'cv2', 'av', 'onnxruntime', 'onnx', 'sklearn', 'nltk', 'sentencepiece', 'PIL', 'timm', 'accelerate', 'datasets', 'evaluate'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='aksal',
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
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='aksal',
)
