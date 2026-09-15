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

# core/geocoder.py("도시별 정리")용 도시 좌표 데이터(assets/geonames_cities1000.csv)는
# 위 datas의 'assets' 통째 포함에 이미 실리므로 별도 collect_all이 필요 없다
# (2026-09-11, reverse_geocoder 패키지 제거 후 — scipy는 PyInstaller 기본
# 훅으로 자동 처리돼 이 목록에 없어도 된다).
#
# 2026-09-13: torch/torchvision/facexlib/open_clip_torch를 전부 뺐다 —
# 화질개선/얼굴복원/디블러/디노이즈 제거로 facexlib(얼굴 탐지) 소비자가
# core/quality_diagnosis.py 하나만 남았었는데, "얼굴이 있어서 흐림" 문구
# 하나 보여주자고 torch+facexlib(약 590MB)를 유지할 이유가 없다고 판단해
# 그 탐지 로직 자체를 없앴다. AI 카테고리(사진 진단 카테고리 판단·카테고리
# 찾기)는 같은 날 ONNX Runtime + 사전 계산된 텍스트 임베딩으로 이미 바뀌어서
# open_clip_torch도 필요 없었다. 이제 이 앱은 torch를 전혀 쓰지 않는다.

# onnxruntime은 AI 카테고리(CLIP 비전 인코더) 추론용(2026-09-13) — hidden import
# 없이도 PyInstaller가 대체로 잘 잡아내지만, C 확장 모듈이라 collect_all로 확실히.
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
    icon=['assets/icon.ico'],
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
