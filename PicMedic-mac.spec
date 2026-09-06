# -*- mode: python ; coding: utf-8 -*-
# macOS 전용 빌드 spec. Windows용 PicMedic.spec과 별도로 관리한다
# (아이콘 .icns, .app 번들 생성이 Windows와 다름). macOS에서만 빌드 가능(크로스 컴파일 불가):
#   pyinstaller PicMedic-mac.spec
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('pillow_heif')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# core/face_restorer.py ("얼굴 복원") 의존성 — basicsr/RestoreFormer는
# vendor/에서 오는 순수 파이썬이라 pathex만 있으면 되고, 나머지는 pip 패키지.
# open_clip_torch는 core/photo_category.py("사진 진단"의 카테고리 판단)용.
for pkg in ('torch', 'torchvision', 'facexlib', 'open_clip'):
    tmp_ret = collect_all(pkg)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=['vendor/basicsr_min', 'vendor/restoreformer'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PicMedic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
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
    name='PicMedic',
)

app = BUNDLE(
    coll,
    name='PicMedic.app',
    icon='assets/icon.icns',
    bundle_identifier='com.picmedic.app',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'NSHighResolutionCapable': True,
    },
)
