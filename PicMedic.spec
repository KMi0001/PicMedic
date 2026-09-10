# -*- mode: python ; coding: utf-8 -*-
# onedir 빌드(RESTORATION_QUALITY_PLAN.md 5-1, 2026-09-11) — --onefile은 실행할
# 때마다 %TEMP%에 통째로(실측 2GB) 압축을 풀어야 해서 콜드 스타트가 약 80초
# 걸렸다. onedir은 dist/PicMedic/ 폴더 전체를 배포하고 실행 파일은 그 폴더의
# 내용을 그대로 읽으므로 매 실행 압축 해제가 없다 — PicMedic-mac.spec(.app 번들)도
# 원래부터 같은 COLLECT 구조였다(macOS는 이 문제 자체가 없었음).
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('pillow_heif')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# core/face_restorer.py ("얼굴 복원") 의존성 — basicsr/RestoreFormer는
# vendor/에서 오는 순수 파이썬이라 pathex만 있으면 되고, 나머지는 pip 패키지.
# open_clip_torch는 core/photo_category.py("사진 진단"의 카테고리 판단)용.
# core/geocoder.py("도시별 정리")용 도시 좌표 데이터(assets/geonames_cities1000.csv)는
# 위 datas의 'assets' 통째 포함에 이미 실리므로 별도 collect_all이 필요 없다
# (2026-09-11, reverse_geocoder 패키지 제거 후 — scipy는 PyInstaller 기본
# 훅으로 자동 처리돼 이 목록에 없어도 된다).
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
    upx=False,  # torch/CUDA DLL은 UPX 압축 시 로딩 실패·백신 오탐 사례가 많고, macOS는 코드서명/공증과 충돌한다 (2026-09-11 리뷰)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,  # torch/CUDA DLL은 UPX 압축 시 로딩 실패·백신 오탐 사례가 많고, macOS는 코드서명/공증과 충돌한다 (2026-09-11 리뷰)
    upx_exclude=[],
    name='PicMedic',
)
