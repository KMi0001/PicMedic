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

# core/geocoder.py("도시별 정리")용 도시 좌표 데이터(assets/geonames_cities1000.csv)는
# 위 datas의 'assets' 통째 포함에 이미 실리므로 별도 collect_all이 필요 없다
# (2026-09-11, reverse_geocoder 패키지 제거 후 — scipy는 PyInstaller 기본
# 훅으로 자동 처리돼 이 목록에 없어도 된다).
#
# 2026-09-13: torch/torchvision/facexlib/open_clip_torch를 전부 뺐다 — 자세한
# 배경은 PicMedic.spec의 같은 날짜 주석 참고. 이제 이 앱은 torch를 전혀 쓰지 않는다.

# onnxruntime은 AI 카테고리(CLIP 비전 인코더) 추론용(2026-09-13).
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
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
    upx=False,  # 네이티브 DLL(onnxruntime 등)은 UPX 압축 시 로딩 실패·백신 오탐 사례가 많고, macOS는 코드서명/공증과 충돌한다 (2026-09-11 리뷰)
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
    upx=False,  # 네이티브 DLL(onnxruntime 등)은 UPX 압축 시 로딩 실패·백신 오탐 사례가 많고, macOS는 코드서명/공증과 충돌한다 (2026-09-11 리뷰)
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
