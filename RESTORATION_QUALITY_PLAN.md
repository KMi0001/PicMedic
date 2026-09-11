# 복원 기능 퀄리티업 계획

> 배경: 유료 배포(스토어 판매)를 검토하다가, 복원 4종(디블러/디노이즈/얼굴복원/화질개선)의
> 완성도가 "돈 받고 팔기엔 아쉽다"는 판단이 나와서(2026-09-08 대화) 무엇을 어디까지
> 손봐야 할지 정리한 작업 계획서. [DESIGN.md](DESIGN.md), [PRD_MVP우선순위.md](PRD_MVP우선순위.md)와
> 같은 성격의 상시 갱신 문서 — 항목을 처리할 때마다 상태를 갱신할 것.

**상태 범례**: ✅ 완료 · 🟡 진행 중 · ⬜ 미착수

---

## 0. 왜 이 문서가 필요한가

4개 복원 기능 모두 "사전학습된 AI 모델을 원본에 그대로 돌린다"는 같은 구조를 쓰지만,
각 모델은 **좁은 학습 도메인**을 가진다 — 학습 데이터와 다른 입력이 들어오면 결과가
예측 불가능하게 나빠질 수 있다. 실제로 2026-09-08에 디블러(NAFNet-GoPro)가 도메인 밖
입력에서 컬러 노이즈로 결과를 망가뜨린 사례가 있었고, 사후에 안전장치를 급히 추가했다
([core/deblur.py](core/deblur.py) 참고). **이 사고가 왜 디블러에서만 막혔고 나머지
3개 기능엔 같은 위험이 그대로 남아있는지**가 이 문서의 핵심 문제의식이다.

목표는 "AI 모델을 더 좋은 것으로 바꾸자"가 아니라 — 지금 채택한 모델(NAFNet, RestoreFormer++,
Real-ESRGAN)은 라이선스/성능 검증을 거쳐 고른 것들이라 교체 우선순위는 낮다 — **"모델이
못 하는 입력을 못 하는 채로 안전하게 실패시키고, 할 수 있는 입력에서는 결과가 실제로
좋은지 검증된 상태로 만드는 것**이다.

---

## 1. 현황 진단 (기능별)

### 1-1. 디블러 — [core/deblur.py](core/deblur.py)
- 모델: NAFNet-GoPro-width32 (Megvii, MIT 라이선스), 합성 모션 블러 데이터셋 전용 학습.
- 안전장치: ✅ 있음 — 사전 점검(`DeblurNotRecommendedError`, 이미 선명하면 거부) +
  사후 점검(`DeblurResultUnstableError`, 출력 edge variance가 원본 대비 10배 넘게
  폭증하면 저장 안 함). 임계값은 `experiments/deblur_safety_prototype/measure.py` 실측 기반.
- 남은 약점: 사전 점검은 "edge variance가 낮은 사진 = 블러"라는 휴리스틱 하나뿐이라,
  하늘/바다처럼 매끈한 비-블러 사진이 여전히 새어 들어갈 수 있다(주석에 이미 명시됨,
  [core/deblur.py:29-33](core/deblur.py:29)). 사후 점검이 마지막 방어선인데 이것도
  "폭증했는지"만 보지 "실제로 더 선명해 보이는지"는 안 본다.

### 1-2. 디노이즈 — [core/denoise.py](core/denoise.py)
- 모델: NAFNet-SIDD-width32, 스마트폰 센서 저조도 노이즈 데이터셋 전용 학습 —
  디블러와 **같은 아키텍처 계열, 같은 종류의 좁은 도메인 리스크**.
- 안전장치: ✅ **완료(2026-09-11)** — 사전 점검(`DenoiseNotRecommendedError`,
  `core.quality_diagnosis.NOISE_RESIDUAL_STDDEV_THRESHOLD` 재사용) + 사후 점검
  (`DenoiseResultUnstableError`, 출력 edge variance가 입력의 1.5배를 넘으면 저장 안 함).
  디블러처럼 과거 사고 실측치를 재사용한 게 아니라 "디노이징은 출력 variance를
  입력보다 늘려선 안 된다"는 원리적 불변식 — `experiments/denoise_safety_prototype/measure.py`
  실측(정상 케이스 ratio 0.14~0.99, 전부 1 미만)으로 뒷받침. 실제 발산 사례가 보고되면
  임계값 재조정 필요.

### 1-3. 얼굴복원 — [core/face_restorer.py](core/face_restorer.py)
- 모델: RestoreFormer++ (Apache 2.0). GFPGAN/CodeFormer는 라이선스 문제로 배제하고
  선택한 모델 — 이 부분 판단은 유지.
- 안전장치: ✅ **완료(2026-09-11)** —
  - `FaceTooSmallError`: 찾은 얼굴이 전부 `core.quality_diagnosis.MIN_FACE_CROP_SIZE`
    (60px, 기존 사진진단 얼굴탐지가 이미 쓰던 기준을 재사용)보다 작으면 저장 안 함.
  - `AnimalPhotoError`: `core.photo_category`의 CLIP 8-카테고리 분류(이미 있던 "동물
    사진" 카테고리 재사용)로 사진 전체가 동물 사진이면 아예 실행하지 않음 — 사용자
    요청("고양이/강아지는 복원대상에서 빼줘")으로 추가.
  - **알려진 한계**: 사람+반려동물이 함께 나온 사진은 전체 분류가 "인물 사진"이라
    이 사전 점검을 통과한다. 얼굴 단위로 동물/사람을 구분해 반려동물 얼굴만
    선택적으로 제외하려면 RestoreFormer 내부 파이프라인(`vendor/restoreformer`)을
    직접 고쳐야 해서(현재는 `enhance(paste_back=True)`가 감지→복원→합성을 한 번에
    처리) 더 큰 작업 — 이번엔 포함하지 않음, 필요성이 확인되면 별도 항목으로.

### 1-4. 화질개선(업스케일) — [core/quality_enhancer.py](core/quality_enhancer.py)
- 모델: Real-ESRGAN x4plus (ncnn-vulkan). NAFNet 계열처럼 좁은 도메인에 갇혀있진 않아
  범용성은 상대적으로 낫다.
- 안전장치: 해당 없음(발산 리스크가 낮은 모델) — 대신 다른 종류의 문제.
- 남은 약점:
  - macOS 바이너리 없음 → `is_available()`이 항상 False, 기능 자체가 반쪽 배포.
  - 코드 주석에 이미 명시된 대로 "이미 고화질인 사진일수록 오래 걸리고 얻는 이득은
    적다"([core/quality_enhancer.py:12-13](core/quality_enhancer.py:12))는데, 이걸
    사용자에게 미리 알려주는 로직이 없다 — 이미 고화질 사진에 4배 업스케일을 돌려서
    시간만 오래 걸리고 체감 효과는 없는 경험을 만들 수 있다.

### 1-5. 테스트 — [tests/test_ai_restoration.py](tests/test_ai_restoration.py)
- 현재 검증 범위: "실행이 죽지 않는지", "원본이 보존되는지", "estimate 함수가 해상도에
  비례하는지"뿐. 테스트 사진도 단색 배경 + 가우시안 블러 합성 이미지 하나뿐이라
  ([tests/test_ai_restoration.py:21-26](tests/test_ai_restoration.py:21)) 실제 손떨림
  사진, 실제 저조도 노이즈 사진, 실제 저해상도 얼굴 사진과는 분포가 다르다.
- **결과 품질(더 선명해졌는지/노이즈가 줄었는지/자연스러운지)을 검증하는 테스트가
  전혀 없다.** 지금은 "코드가 안 죽는다"만 보장하지 "복원이 잘 됐다"는 아무도
  확인하지 않는 상태.

---

## 2. 우선순위별 개선 항목

### P0 — 사고 재발 방지 (판매 전 필수)

- [x] **디노이즈에 디블러와 동일한 안전장치 이식** (2026-09-11 완료) — [1-2](#1-2-디노이즈--coredenoisepy) 참고.
- [x] **얼굴복원 최소 품질 게이트 + 동물 사진 제외** (2026-09-11 완료) — [1-3](#1-3-얼굴복원--coreface_restorerpy) 참고.

### P1 — 신뢰도 검증 체계 (있어야 "된다"고 말할 수 있음)

- [x] **비교 스크립트 뼈대** (2026-09-11) — [experiments/restore_quality_goldset/compare.py](experiments/restore_quality_goldset/compare.py)
  로 4개 기능을 기존 샘플에 돌려 원본|결과 나란히 붙인 PNG를 만드는 구조는 만들었다.
- [ ] **진짜 실사진으로 교체 — 아직 안 됨, 확인해보니 기존 샘플은 전부 합성/일러스트였다**
  - 실행해서 실제로 눈으로 봤더니(2026-09-11): `experiments/city_organize_prototype/
    sample_photos/*.jpg`(busan.jpg 등)는 **단색 하늘색 배경 하나뿐인 합성 이미지**였고,
    `experiments/restore_prototype/test_images/old_blurry_portrait.jpg`는 **실제 사진이
    아니라 평면 벡터 일러스트 얼굴**이었다(그래서 face_restorer가 `NoFaceFoundError`를
    던짐 — RetinaFace는 실사진 얼굴로 학습된 모델이라 일러스트에서는 얼굴을 못 찾는 게
    당연한 결과). 즉 지금까지 "샘플"이라고 불러온 것들이 전부 실제 사진이 아니었다 —
    [1-5](#1-5-테스트--testtest_ai_restorationpy)에서 짐작만 했던 문제가 실측으로 확정됨.
  - **다음 사람이 할 일**: 저작권 문제 없는 진짜 사진(본인 촬영 또는 CC0)으로 —
    실제 손떨림 사진 5~10장, 실제 저조도 노이즈 사진 5~10장, 다양한 크기/각도의
    인물 사진 5~10장 — `experiments/restore_quality_goldset/`에 넣고
    `compare.py`의 `CANDIDATES`를 실제 경로로 바꿔야 이 항목이 비로소 의미가 있다.
  - 용도: 모델/임계값을 바꿀 때마다 이 골드셋으로 돌려서 "이전보다 나빠지지 않았는지"를
    비교하는 회귀 기준점으로 쓴다.

- [x] **Before/After 시각 비교 리포트 스크립트** (2026-09-11) — 위 `compare.py`가
  이 역할. 골드셋이 진짜 사진으로 채워지면 그대로 재실행만 하면 됨.
  - 목적은 자동 판정이 아니라 **사람이 눈으로 훑어보고 "이 정도면 팔 만하다" 판단을
    내릴 수 있는 근거 자료**를 만드는 것. 스토어 심사/마케팅용 스크린샷도 여기서 나올 수 있음.

- [ ] **정량 지표 보조 도입 (선택)**
  - 육안 검토를 대체하진 않지만 보조 지표로 SSIM/PSNR 같은 표준 화질 지표를 골드셋에
    대해 찍어두면, 나중에 모델을 바꾸거나 튜닝할 때 "감覚"이 아니라 숫자로 비교 가능.
  - 우선순위는 낮음 — 골드셋 기반 육안 검토가 먼저 갖춰진 뒤에 고려.

### P2 — 배포 완성도

- [ ] **macOS Real-ESRGAN 바이너리 확보**
  - `scripts/fetch_realesrgan_assets.py`가 Windows 실행 파일만 받아오는 구조를
    macOS ncnn-vulkan 빌드도 받아오도록 확장(공식 릴리스에 macOS 바이너리 존재 여부 확인 필요).
  - [PicMedic-mac.spec](PicMedic-mac.spec) 빌드 시 자산 포함 여부도 같이 점검.

- [ ] **"이미 고화질" 사전 안내**
  - `enhance_quality` 실행 전, 입력 해상도가 이미 충분히 높으면(기준 실측 필요) 확인
    팝업에서 "이 사진은 이미 고화질이라 효과가 크지 않을 수 있어요"라고 안내 —
    거부는 아니고 정보 제공.

---

## 3. 검증 방법론 (기존 패턴 재사용)

디블러 안전장치를 만들 때 쓴 방식을 표준 절차로 삼는다:

1. `core/*.py`에 바로 손대지 않고 `experiments/<기능>_safety_prototype/measure.py`로
   먼저 실측 (기존 [experiments/deblur_safety_prototype/measure.py](experiments/deblur_safety_prototype/measure.py) 참고).
2. "정상 케이스"와 "망가지는 케이스"의 지표 차이가 실측으로 명확히 갈리는지 확인
   (디블러는 정상 1.03배 vs 망가짐 43.82배로 여유 있게 갈렸음).
3. 임계값을 중간값보다 보수적으로 잡아서(정상 케이스에 여유를 두는 쪽으로) 오탐보다
   미탐을 우선 줄인다 — 사용자에게 "실패"로 보이는 것보다 "망가진 결과가 저장되는 것"이
   더 나쁘다는 판단 기준 유지.
4. 검증 후에만 `core/*.py`에 반영 + 이 문서와 해당 모듈 docstring에 실측 근거 기록.

---

## 4. 로드맵 (권장 순서)

1. ~~**디노이즈 안전장치** (P0)~~ — 2026-09-11 완료.
2. ~~**얼굴복원 최소 크기 게이트 + 동물 사진 제외** (P0)~~ — 2026-09-11 완료.
3. **골드셋 + Before/After 리포트** (P1) — 아직 미착수. 1·2번을 검증할 근거이자, 이후
   모든 튜닝의 기준점 — 다음으로 손볼 항목.
4. **macOS 바이너리 / 안내 문구** (P2) — 배포 완성도, 품질 자체와는 별개라 나중에 처리해도 무방.

이 로드맵이 끝나면 "복원 기능이 실패할 땐 안전하게 실패하고, 성공할 땐 골드셋으로
검증된 품질을 낸다"는 근거를 갖고 유료 전환 여부를 다시 판단할 수 있다.

---

## 5. 복원 외 유료화 준비 항목

복원 품질과 별개로, "exe를 실제로 빌드해서 스토어에 낸다"는 흐름 자체를 점검하다가
발견한 항목들. 모델 튜닝보다 먼저 막혀도 이상하지 않은 부분들이라 같이 기록해둔다.

### 5-1. 🟡 패키징 용량/시작 속도 — 실측 완료, 조치 필요
- **실측(2026-09-11, `pyinstaller PicMedic.spec`, CPU 전용 torch 기준)**:
  - exe 용량: **1.3GB**.
  - 콜드 스타트: 실행 파일 실행 → onefile 압축 해제 완료(자식 프로세스 기동) 까지
    **약 80초**, 그 뒤 창이 뜨기까지 추가 시간(측정 안 함, Qt 자체 기동은 빠를 것으로
    예상). `%TEMP%\_MEIxxxxx`로 풀린 크기는 **2GB**(exe보다 큼 — 압축 해제된 상태라).
    이건 CUDA torch가 아니라 CPU 전용 torch 기준이라, CUDA 빌드로 바꾸면 용량이 더
    커질 수 있다(5-2 참고).
  - **결론: `--onefile`은 이 규모에서 첫 실행 경험을 확실히 해친다.** "앱을 눌렀는데
    1분 넘게 아무 반응이 없다"는 건 유료 소프트웨어에서 리뷰 테러 사유가 되기 쉽다.
  - 조치: `--onedir`(폴더 배포)로 전환 — 압축 해제가 설치 시 한 번만 일어나고 실행마다
    반복되지 않는다.
- ✅ **조치 완료·재측정 완료(2026-09-11)** — `PicMedic.spec`/`PicMedic-mac.spec`(macOS는
  원래부터 이 구조였음)에 `EXE(..., exclude_binaries=True)` + `COLLECT(...)`로 전환.
  재빌드해서 실측: **콜드 스타트 80초 → 4.2초로 개선**(약 19배). `dist/PicMedic/
  PicMedic.exe` 자체는 62.5MB로 작아졌고(부트로더만 남음), 나머지는 옆의 `_internal/`
  폴더에 있음 — **배포 시 exe 파일 하나만 옮기면 실행 안 됨, 폴더 전체를 같이
  배포해야 함**(README.md에 반영함). `logs/`·기본 저장 위치는 `sys.executable` 기준
  경로라 onedir에서도 그대로 "exe 옆"에 생성됨(코드 변경 불필요, 확인함).
  - ⚠️ **이 마지막 문장은 2026-09-11 리뷰에서 뒤집혔다** — "exe 옆"이 바로 문제였다.
    5-7 참고(사용자별 앱 데이터 폴더로 옮김).

- ✅ **UPX 끈 뒤 재빌드 검증(2026-09-11)** — 빌드 성공, `PicMedic.exe` 실행해서
  프로세스가 정상 기동하는 것까지 확인(143MB 상주). **Windows Defender 전체 스캔
  결과 위협 0건** (`MpCmdRun.exe -Scan -ScanType 3`) — UPX를 켜뒀을 때 흔한 백신
  오탐이 이 빌드에는 없다. 다른 백신 엔진(스토어 심사에서 쓰는 것 포함)까지
  보증하는 건 아니지만, 켜둘 이유가 없다는 판단은 유지.

- 🔴 **용량 재실측(2026-09-11, UPX 끈 뒤 CUDA torch 기준): 5,659MB.** 위 1.3GB는
  CPU 전용 torch 기준이었고, 5-2에서 GPU 가속을 위해 CUDA 휠로 바꾸면서 4배 넘게
  뛰었다. `dist/PicMedic/_internal/` 구성:

  | 항목 | 용량 | 비중 |
  |---|---:|---:|
  | `torch/lib` — CUDA 런타임 DLL (torch_cuda 1,060MB, cublasLt 531MB, cudnn 513MB, cusparse 287MB, cufft 277MB, …) | ~3,600MB | 64% |
  | `torch/lib/torch_cpu.dll` + 나머지 torch | ~425MB | 8% |
  | `assets/` — AI 모델 가중치(face_restore 467, photo_category 338, denoise 112, deblur 66, realesrgan 39) | 1,028MB | 18% |
  | llvmlite 115 / cv2 99 / PySide6 93 / scipy 51 / 기타 | ~500MB | 10% |

  **결론: 용량 문제는 사실상 "CUDA torch를 넣을 것인가" 하나로 수렴한다.** CPU 전용
  torch로 되돌리면 약 3.5GB가 빠져 2.2GB 수준이 된다(예전 실측과 일치). 그런데 5-2
  실측으로 GPU 이득은 **실제 폰카 해상도(12MP)에서 1.7배**에 그쳤다 — "고객 전원에게
  3.5GB를 더 받게 하고 1.7배"가 맞는 거래인지가 판단 지점이며, **이건 제품 결정이라
  사용자가 정해야 한다.**

- ✅ **결정: CPU 전용 torch로 확정(2026-09-11, 사용자 판단 "3.5GB에 비해 너무 약소하다").**
  dev 환경도 `torch==2.14.0+cpu` / `torchvision==0.29.0+cpu`로 교체했고(설치 크기
  4,250MB → 534MB), 5-9의 디코딩 수정과 합치면 **CPU만으로도 예전 GPU 빌드보다 빠르다**
  (고양이 찾기 3만 장: 예전 GPU 67분 → 지금 CPU 47분). 코드는 한 줄도 안 고쳤다 —
  [core/torch_device.py](core/torch_device.py)가 CUDA → MPS → CPU 순으로 자동 감지해서
  CPU로 폴백하고, CUDA torch를 깐 개발 환경에서는 여전히 GPU를 쓴다(macOS의 MPS도
  추가 용량 없이 그대로 동작). README 빌드 절에 "CUDA torch로 빌드하지 말 것" 경고를 넣었다.
  - ✅ **재빌드 실측: 5,659MB → 2,104MB** (−3,555MB, 63% 감소). 실행 정상 확인
    (140MB 상주), Windows Defender 전체 스캔 위협 0건. 남은 구성은
    `assets` 1,028MB(49%) · `torch` 481MB · `llvmlite`
    115MB · `cv2` 99MB · `PySide6` 93MB · 나머지.
  - **이제 가장 큰 덩어리는 AI 모델 자산(1,028MB, 전체의 절반)이다** — 다음으로
    용량을 줄이려면 아래 "첫 사용 시 내려받기" 항목이 유일한 큰 수단이고,
    그것까지 하면 본체가 약 1.1GB가 된다.

  - (대기) **AI 자산 1,028MB를 첫 사용 시 내려받기로 분리** — 두 시나리오 모두에서
    유효한 절감이라 언젠가는 할 일이지만, 1GB짜리 최초 실행 다운로드 흐름은
    진행률·오프라인·실패 재시도 UX가 붙는 기능이라 저장소 규칙상
    `experiments/`에 프로토타입을 먼저 만들어 검증받아야 한다.
  - (대기) **안 쓰는 무거운 패키지 제외** — `pandas`/`matplotlib`/`numba`/`llvmlite`는
    앱 코드에서 직접 import하는 곳이 0곳이고, `open_clip_torch`/`facexlib`/
    `scikit-image`의 선택적 의존으로 딸려 들어온 것들이다(약 145MB). 다만
    `collect_all`이 넣은 걸 빼면 런타임에만 드러나는 방식으로 깨질 수 있어,
    빼고 재빌드해서 AI 기능을 실제로 돌려보는 검증이 필요하다. 전체의 2.5%라
    CUDA 결정 뒤로 미룸. `cv2`는 실제로 10곳에서 쓰므로 제외 대상이 아니다.

### 5-2. ✅ "GPU 자동 감지"가 실제로 GPU 빌드를 쓰는지 — 배포는 CPU로 확정됨(5-1 참고)

> **2026-09-11 후속**: 아래 조사·실측은 그대로 유효하지만, **배포 빌드는 CPU 전용
> torch로 확정됐다**(5-1). 여기서 잰 "1.7배"가 그 결정의 근거였고, 5-9에서 진짜
> 병목이 GPU가 아니라 JPEG 디코딩이었다는 게 밝혀지면서 결정이 더 분명해졌다.
> `core/torch_device.py`의 자동 감지 로직 자체는 유지된다 — 개발 환경에 CUDA
> torch를 깔면 그대로 GPU를 쓰고, macOS의 MPS는 추가 용량 없이 계속 동작한다.

- **판정 로직 자체는 2026-09-11에 고쳤다** — [core/torch_device.py](core/torch_device.py)
  `resolve_device()`(`cuda → mps → cpu` 순)를 만들어 기존 6곳(deblur/denoise/
  face_restorer/quality_diagnosis/photo_category/cat_finder)에 흩어져 있던
  `torch.device("cuda" if torch.cuda.is_available() else "cpu")` 중복을 전부
  교체했다. macOS의 Apple Silicon GPU(MPS)를 이제 코드상으로는 쓸 수 있다.
- **다만 배포 설정 문제는 여전히 남아있고, 실측으로 확인됐다.** 이 개발 환경에서
  `python -c "import torch; print(torch.__version__)"` 결과가 **`2.14.0+cpu`** —
  CUDA 빌드가 아니다. [requirements.txt](requirements.txt)의 `torch>=2.0`은 버전만
  지정하고 CPU/CUDA 빌드를 지정하지 않아서, 기본 `pip install`로 만든 환경 그대로
  Windows exe를 빌드하면 **exe에도 CPU 전용 torch가 담긴다** — `resolve_device()`가
  아무리 올바르게 판정해도 애초에 `torch.cuda.is_available()`이 항상 False라 GPU
  가속을 전혀 못 쓴다.
- ✅ **완료·실측 검증까지 끝남(2026-09-11)**. 처음엔 `cu121`/`cu124` 인덱스만 확인하고
  "Python 3.14는 공식 CUDA 휠 자체가 없다"고 잘못 결론 내렸었다 — 실제로는
  **`cu126`/`cu128` 인덱스에 Python 3.14(cp314) + torch 2.14.0 CUDA 빌드가 정확히
  있었다**(`torch-2.14.0+cu126-cp314-cp314-win_amd64.whl`). 확인 범위가 부족해서
  생긴 오판이었다 — 다음에 비슷한 걸 확인할 땐 cu121/124뿐 아니라 cu126/128까지
  다 훑을 것.
  - 설치: `pip install torch==2.14.0+cu126 torchvision --index-url
    https://download.pytorch.org/whl/cu126`(torchvision은 버전을 안 박으면 기존
    CPU 빌드가 그대로 남는 함정이 있어 `--force-reinstall`로 한 번 더 맞춰야 했음).
  - 검증: `torch.cuda.is_available()` → `True`, `torch.cuda.get_device_name(0)` →
    `NVIDIA GeForce RTX 3060 Ti`(이 머신에 실제 GPU가 있었음, `nvidia-smi`로 사전
    확인). `core/torch_device.resolve_device()`도 `cuda`를 정확히 고름.
  - `tests/test_ai_restoration.py`(12/12)·`test_photo_category.py`·
    `test_quality_diagnosis.py` 전부 GPU 빌드에서도 0 실패.
  - **실측 속도 비교, 두 가지 해상도**(`core/deblur.py`):
    - 원본 크기(720x900, 작은 테스트 이미지): CPU 11.47초 → GPU 1.22초 (**약 9.4배**).
    - **12MP(4032x3024, 요즘 폰카 실제 해상도)로 키운 같은 사진**: CPU 160.00초 →
      GPU 94.05초 (**약 1.7배뿐**).
    - **작은 이미지에서 본 "9.4배"를 실제 사용자 체감으로 오해하면 안 된다** — 해상도가
      커질수록 GPU 이득이 급격히 줄어든다(9.4배 → 1.7배). NAFNet(width=32) 아키텍처가
      큰 텐서 하나를 통째로 돌리는 방식이라, 해상도가 커질수록 연산보다 메모리
      이동/대역폭이 병목이 되는 것으로 보인다(타일링 등 최적화는 안 되어 있음 —
      추가 조사·최적화는 이번 범위 밖, 필요하면 별도 항목으로 뺄 것).
    - **`estimate_seconds()`의 GPU 미반영 문제** — [core/deblur.py:67-70](core/deblur.py:67)의
      예상 시간 공식은 CPU 실측(0.5초 고정 + 5초/MP)만 반영돼 있고 GPU 여부를
      전혀 구분하지 않는다. GPU 사용자에게도 "12MP면 약 60초"라고 안내하게 되는데,
      실측(94초, 위 참고)을 보면 GPU라고 크게 빠르지도 않아서 이 부분은 표시 문구
      자체는 당장 급하지 않아 보이지만, 그렇다고 CPU 공식이 GPU에 맞는 것도 아니다 —
      추후 실제 사용자 피드백을 보고 조정할 항목으로 남겨둠.
  - 결론: GPU 자동 감지 체인(판정 로직 → 실제 GPU 빌드)은 전부 작동을 확인했지만,
    **"GPU면 훨씬 빠르다"는 기대는 최소한 디블러(NAFNet)에서는 해상도가 커질수록
    많이 꺾인다** — 화질개선(Real-ESRGAN)·얼굴복원(RestoreFormer++)은 아키텍처가
    달라 같은 정도로 꺾이는지는 이번에 확인 못 함. 배포용 빌드 환경엔 이 방식(torch
    버전에 맞는 `cuXXX` 인덱스 지정, 필요시 torchvision도 같이 `--force-reinstall`)을
    그대로 적용하면 된다 — README.md에 반영.

### 5-3. 🟡 오픈소스 라이선스 고지 누락 — 실제 의존성 라이선스 전수 확인, 새 위험 하나 발견
- 확인됨: 저장소 최상위는 물론 `vendor/basicsr_min`, `vendor/restoreformer`(둘 다 이
  저장소가 직접 벤더링한 코드)에도 `LICENSE`/`NOTICE` 파일이 **하나도 없다** — pip로
  설치되는 패키지들은 site-packages 안에 자체 라이선스 파일을 갖고 있지만, 벤더링한
  코드와 최종 배포물(exe)에는 아무 라이선스 고지도 따라가지 않는다.
- **실제 설치된 패키지 메타데이터로 라이선스를 하나씩 확인**(2026-09-11,
  `importlib.metadata`로 실측 — 표로 남김):

  | 패키지 | 라이선스 | 비고 |
  |---|---|---|
  | torchvision | BSD | |
  | facexlib | Apache 2.0 | |
  | open-clip-torch | MIT | |
  | opencv-python | Apache 2.0 | |
  | pillow-heif | BSD-3-Clause | |
  | torch, pillow, numpy | (메타데이터에 필드 없음) | 각각 BSD류로 알려져 있으나 메타데이터로는 확인 안 됨 — 공식 저장소 LICENSE로 재확인 필요 |
  | **reverse_geocoder** | **LGPL** | **아래 참고 — 지금까지 검토한 MIT/Apache 계열과 다른 종류라 새로 발견된 위험** |

- **새로 발견된 위험: `core/geocoder.py`("도시별 정리" 기능)가 의존하는
  `reverse_geocoder`가 LGPL이다.** 지금까지 이 문서와 `feedback_check_commercial_license`
  메모가 검토해온 건 MIT/Apache 계열(재배포 시 고지만 하면 됨)뿐이었는데, LGPL은
  결이 다르다 — 상업적 이용 자체는 허용되지만, PyInstaller `--onefile`처럼 라이브러리를
  실행 파일 하나로 정적으로 합쳐 배포하는 방식이 LGPL이 요구하는 "사용자가 이
  라이브러리만 교체/재연결할 수 있어야 한다"는 조건과 어떻게 맞물리는지는 법률
  검토가 필요한 영역이다(나는 변호사가 아니라 여기서 결론을 낼 수 없음). 조치 후보:
  (a) 법률 자문으로 현재 배포 방식이 문제없는지 확인, 또는 (b) MIT/Apache 계열의
  대체 오프라인 역지오코딩 라이브러리로 교체(`core/geocoder.py`가 GeoNames 파생
  CSV 최근접 탐색만 하는 단순한 구조라 교체 자체의 기술 난이도는 낮아 보임).
- 나머지(NAFNet MIT, RestoreFormer++ Apache 2.0, basicsr Apache 2.0 — 전부
  [core/face_restorer.py:10-12](core/face_restorer.py:10) 등 코드 주석에 이미
  근거가 남아있음)는 상업적 이용 자체는 문제없다고 이미 판단됐고, MIT/Apache는
  재배포 시 저작권 고지·라이선스 사본 포함만 요구한다. 지금처럼 코드 주석에만
  출처가 남아있고 최종 사용자에게 전달되는 배포물(exe)이나 스토어 페이지에 고지가
  없으면 이 부분도 라이선스 조건 미준수 상태다.
- 조치: (1) reverse_geocoder LGPL 건 먼저 정리(법률 검토 또는 교체 — 아래 참고),
  (2) 나머지 MIT/Apache 계열은 앱 정보/도움말 화면이나 별도 `THIRD_PARTY_NOTICES.txt`를
  exe에 포함시켜서 라이선스 전문과 저작권 고지를 나열. 스토어 심사에서 직접 요구하지
  않아도 법적으로는 필요.
- **(1) ✅ 완료(2026-09-11)**: `reverse_geocoder` 패키지(LGPL 코드는 `__init__.py`+
  `cKDTree_MP.py` 합쳐 15KB 남짓의 얇은 래퍼뿐 — 실제 데이터는 GeoNames 파생이라
  CC-BY 4.0이고 LGPL과 무관)를 프로토타입([experiments/geocoder_license_prototype/](experiments/geocoder_license_prototype/),
  8/8 좌표 완전 일치 검증)으로 먼저 확인한 뒤 `core/geocoder.py`에 실제로 통합했다.
  - 데이터를 `assets/geonames_cities1000.csv`로 옮기고 `scipy.spatial.cKDTree`(BSD,
    requirements.txt에 명시 추가 — reverse_geocoder를 통해 간접 설치되던 걸 놓칠
    뻔해서 직접 못 박음)로 전세계 인덱스 하나를 만들어 재사용, 기존 한국 지역
    보정(`_get_kr_only_index`, 백령도 국경 오탐 수정)은 그 인덱스를 공유하도록
    리팩터링만 하고 로직은 그대로 유지.
  - `requirements.txt`/`PicMedic.spec`/`PicMedic-mac.spec`에서 `reverse_geocoder`
    제거, `THIRD_PARTY_NOTICES.txt`에 GeoNames 데이터 저작자 표시(CC-BY 4.0) 추가.
  - **이 모듈은 그동안 테스트가 하나도 없었다** — [tests/test_geocoder.py](tests/test_geocoder.py)를
    새로 만들어 서울/부산/뉴욕/파리 매칭, 백령도 국경 오탐 보정, 배치 조회 순서
    일치까지 7개 케이스로 고정. 전체 테스트 스위트(`test_*.py` 전부) 재실행해서
    0 실패 확인.
- **(2) 진행 상황(2026-09-11)**: [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) 초안
  작성 완료 — NAFNet/BasicSR/RestoreFormer++/facexlib/Real-ESRGAN/open_clip/
  torchvision/pillow-heif/opencv-python까지, 라이선스 종류는 pip 메타데이터로 실측
  확인. torch/numpy/Pillow 세 개는 메타데이터에 필드가 없어 공식 저장소 링크만
  남겨두고 배포 전 재확인이 필요하다고 명시했다. reverse_geocoder는 (1)이 정리되기
  전까지 이 목록에서 제외.

### 5-4. ⬜ MS 스토어 제출 요건 체크리스트 부재 — 구체 항목으로 보강
- 저장소 안에 개인정보처리방침(Privacy Policy) URL, 연령 등급 설문 답변, 지원
  이메일/문의처, EULA 초안 등 스토어 제출에 필요한 문서가 보이지 않는다. 무료일 땐
  건너뛸 수 있었어도 **유료 전환 시 Partner Center는 개인정보처리방침 URL을 모든
  앱에 필수로 요구**한다(무료/유료 무관 — 유료는 여기에 결제 관련 고지가 추가로 필요).
- **Partner Center 제출 흐름에서 실제로 막힐 수 있는 항목들** (일반적인 Microsoft
  Store 정책 기준 — PicMedic 전용 확정 요건은 실제 제출 시 화면에서 최종 확인 필요):
  1. **개인정보처리방침 URL** — 반드시 실제로 접속 가능한 공개 URL(정적 페이지 하나로
     충분). 이 앱은 로컬 파일만 다루고 외부로 사진/위경도를 보내지 않는 구조라
     ([core/geocoder.py:7-9](core/geocoder.py:7)에 이미 "이 프로세스 밖으로 절대
     안 나감" 원칙이 명시돼 있음), 정책 문서에 그대로 반영하면 신뢰 포인트가 된다.
     단, 5-6의 옵트인 원격 로그를 나중에 추가하면 그 항목도 정책에 명시해야 함.
  2. **연령 등급 설문(IARC)** — Partner Center 제출 화면에서 매번 새로 answer해야
     하는 설문. 폭력/성인/도박성 콘텐츠 없음으로 답하면 대체로 낮은 등급이 나오지만
     설문 자체를 안 하면 제출이 막힌다 — 문서로 준비할 항목이 아니라 제출 시점에
     직접 답해야 함, 체크리스트에 "제출 당일 처리"로 남겨두면 됨.
  3. **지원 연락처** — 이메일 또는 웹사이트 URL 중 최소 하나, 앱스토어 상세 페이지에
     노출됨. 지금 저장소/README에 이런 연락처가 없다 — 준비 필요.
  4. **스크린샷/설명 문구** — 최소 1장(권장 4장 이상), 지원 해상도 규격 있음. 실행
     화면을 캡처하면 되므로 기술적 난이도는 낮음.
  5. **EULA** — 커스텀 EULA를 안 쓰면 Microsoft 표준 라이선스 약관이 자동 적용됨(대부분
     앱은 이걸로 충분). 커스텀이 필요한 이유(예: 5-3의 제3자 라이선스 고지를 EULA에
     같이 넣고 싶다면)가 없으면 굳이 새로 쓸 필요는 없음 — 우선순위 낮음.
- 조치: 제출 전 체크리스트로 정리 — 개인정보처리방침 페이지(작성 필요), 지원 연락처
  (이메일 하나면 충분), 스크린샷 4장 이상, 연령 등급은 제출 당일 처리.
- **진행 상황(2026-09-11)**: [PRIVACY_POLICY_DRAFT.md](PRIVACY_POLICY_DRAFT.md) 초안
  작성 완료 — 이 앱이 실제로 사진/위경도를 로컬에서만 처리하고 외부로 전송하지
  않는다는 점을 중심으로 작성. 아직 공개 URL로 호스팅되지 않았으니(정적 페이지로
  옮겨야 함) 실제 제출 전에는 URL이 필요. 5-6(옵트인 실패 로그)을 나중에 추가하면
  이 문서도 같이 갱신해야 함(문서 상단에 메모해둠).

### 5-5. ✅ "원본은 절대 건드리지 않는다" 약속의 예외 경로 커버리지 — 실제 버그 발견·수정·검증 완료(2026-09-11)
- **복원 4종(디블러/디노이즈/얼굴복원/화질개선)은 구조적으로 안전하다** — 원본을
  항상 읽기 전용으로만 열고 결과는 전혀 다른 새 경로에만 쓰므로, 어떤 예외가 나도
  원본을 건드릴 방법 자체가 없다. 이건 코드 구조로 이미 증명되는 부분이라 별도
  실험 없이 결론 남김.
- **진짜 위험은 `core/converter.py`의 `replace_original=True`("원본 삭제" 옵션)
  경로였다** — 여기는 원본을 실제로 옮긴다(먼저 같은 폴더 임시휴지통으로 이동 →
  그 자리에 결과물 저장). 이 함수의 문서화된 약속은 "실패하면 옮겨둔 원본을 즉시
  되돌린다"였는데, **실제로 재현해보니 지켜지지 않는 경로가 있었다**:
  `_recover_file_replacing_original()`이 내부에서 부르는 `recover_file()`이
  (이미 처리 중인 `OSError`가 아니라) **예상 못한 예외**를 던지면, 그 예외가 함수
  전체를 그냥 뚫고 나가버려서 "실패 시 원본 복원" 코드 자체가 실행되지 않았다 —
  원본이 임시휴지통에 방치된 채 아무도 되돌리지 않는 상태. `unittest.mock.patch`로
  실제 재현 확인 후 [core/converter.py](core/converter.py)의 `recover_file()` 호출을
  try/except로 감싸 예외 경로에서도 즉시 복원하도록 수정, [tests/test_converter.py](tests/test_converter.py)
  20~24번에 회귀 테스트로 고정(수정 전 재현 → 수정 후 통과 확인, `test_converter.py`
  53/53 통과).
  - 다행히 "데이터 유실"까지는 아니었다 — `utils/trash.py`의 임시휴지통은 원본 폴더
    바로 옆에 있고 매니페스트로 원래 경로를 기억하는 구조라, 버그가 있던 상태에서도
    파일 자체는 찾을 수 있었다(`gui/trash_screen.py`에서 수동 복원 가능). 다만
    "복구했더니 사진이 원래 자리에서 사라진 것처럼 보인다"는 건 유료 신뢰에 치명적인
    경험이라 자동 복원이 실제로 지켜지는 게 중요했다.

### 5-6. ⬜ 배포 후 실패율을 알 방법이 없음 — 구체 설계로 보강
- 지금은 로컬 `logs/picmedic_log.jsonl`만 있고([README.md:125-128](README.md:125)),
  개발자에게 전달되는 원격 신호가 전혀 없다. 유료 전환 후 "고객 컴퓨터에서 얼마나
  자주 `DeblurResultUnstableError`/`DenoiseResultUnstableError`/`AnimalPhotoError`
  등이 발생하는지"를 알 방법이 없어서, 이번에 추가한 안전장치들이 실제로 효과가
  있었는지(너무 자주 걸려서 오탐이 많은 건 아닌지, 반대로 거의 안 걸려서 굳이 필요
  없었는지)도 사후 검증이 안 된다.
- **구체 설계 제안** (구현은 아직 안 함 — 다음에 착수할 때 이 설계부터 검토):
  - 전송 대상: 예외 클래스 이름(`"DenoiseResultUnstableError"`) + 발생 지점(모듈명)
    + 앱 버전 + OS 종류(Windows/macOS)뿐. 사진 내용/파일명/경로/위경도는 **코드 레벨에서
    아예 수집 대상에 포함하지 않는다**(수집 후 필터링이 아니라, 애초에 그 값을 읽지
    않는 함수로 설계 — core/geocoder.py의 "이 프로세스 밖으로 안 나감" 원칙과 같은
    수준의 보장).
  - 트리거: 설정 화면에 "실패 진단 정보를 개발자에게 보내 품질 개선에 도움주기"
    체크박스(기본값 꺼짐, 완전 옵트인) — 켠 사용자에 한해 위 4개 필드만 전송.
  - 전송 시점: 예외가 GUI의 `no_effect`/`failed` 경로로 잡히는 시점([gui/single_ai_action.py](gui/single_ai_action.py)
    `_Worker.run()`의 `except Exception` 블록 — 지금 이미 모든 실패가 여기로
    모이므로, 훅을 하나 추가하는 정도로 끝날 가능성이 높음).
  - 서버: 처음엔 Google Forms/간단한 서버리스 엔드포인트 하나로도 충분 — 집계
    대시보드까지는 초기 단계에 필요 없음, "가끔 로그를 직접 열어보는" 수준으로 시작.
  - 이건 스토어 개인정보처리방침에도 명시해야 하는 사항이라 5-4번과 같이 처리.

---

### 5-7. ✅ 배포 환경에서만 터지는 경로 3종 — 코드 리뷰로 발견·수정·검증 완료(2026-09-11)

전체 코드 리뷰 중 나온 항목들. 셋 다 **로컬에서 `python main.py`로 개발할 때는
절대 재현되지 않고**, 실제 배포본에서만 나타나는 종류라 따로 묶어 기록한다.

- **로그를 실행 파일 옆에 쓰고 있었다 → 스토어 설치본은 검사가 통째로 멈춘다.**
  [utils/logger.py](utils/logger.py)가 frozen일 때 `Path(sys.executable).parent/logs`를
  썼는데, MS 스토어(MSIX/WindowsApps)나 Program Files는 그 폴더가 읽기 전용이라
  `mkdir`/`open`이 `PermissionError`를 던진다. 그런데 `log_scan()`을 부르는
  [core/scanner.py](core/scanner.py)의 `scan_paths`에 try가 없어서, 그 예외가
  `ScanWorker.run()`까지 그대로 올라가고(아래 항목) **검사가 끝나는 순간 결과가
  통째로 날아간 채 진행 화면이 멈춘다.** 사용자별 앱 데이터 폴더로 옮기고
  `_write`/`read_recent_entries`를 예외에 안전하게 고침. 회귀 테스트는
  [tests/test_logger.py](tests/test_logger.py) 4번(쓰기 불가 경로에서도 예외 없음).
  - `logs/`를 옮기면서 확인한 것: 기본 복구 저장 위치는 이미 원본 폴더 옆
    `Recovered/`라 이 문제와 무관했다(README 설명이 낡아 있어 같이 고침).

- **주요 워커 4개의 `run()`에 try/except가 없어, 예외 = 영구 멈춤이었다.**
  `ScanWorker`, `RecoveryWorker`, `_OrganizeWorker`, `_LightListWorker` —
  예외가 새면 `finished` 시그널이 아예 발생하지 않는다. 특히 뒤 세 개는 모달
  진행 팝업(`ProgressDialog.exec()`)을 띄운 상태라 `accept()`가 영영 안 불려서
  **앱 전체가 잠긴다**(창을 닫을 수도 없다 — `closeEvent`가 워커가 도는 줄 알고
  막는다). 이미 올바른 패턴이던 [gui/single_ai_action.py](gui/single_ai_action.py)의
  `_Worker`를 기준으로 넷 다 `failed` 시그널을 추가하고, 각 화면에 팝업을 닫고
  들어온 곳으로 돌려보내는 실패 핸들러를 붙였다.

- **UPX 압축(`upx=True`)이 두 spec에 켜져 있었다.** torch/CUDA DLL은 UPX로 누르면
  로딩 실패·백신 오탐 사례가 잦고, macOS는 코드서명/공증과 충돌한다. 유료 배포
  직전이라 양쪽 다 `False`로 껐다([PicMedic.spec](PicMedic.spec),
  [PicMedic-mac.spec](PicMedic-mac.spec)) — 다음 빌드 때 용량 변화와 백신 스캔을
  같이 확인할 것.

- (같이 고친 것) [core/quality_enhancer.py](core/quality_enhancer.py)의
  `subprocess.Popen`에 `CREATE_NO_WINDOW`가 없어 windowed 빌드에서 화질 개선을
  누르면 검은 콘솔 창이 떴다. `encoding` 미지정으로 한글 Windows 로캘에서 진행률
  파싱이 깨질 수 있던 것도 같이 처리.

### 5-8. ✅ 진단 결과가 옆 창의 작업 타이밍에 따라 달라지던 버그(2026-09-11)

`ImageFile.LOAD_TRUNCATED_IMAGES`는 이미지별 옵션이 아니라 **Pillow 프로세스 전역
플래그**인데, [core/analyzer.py](core/analyzer.py)와 [core/converter.py](core/converter.py)가
각자 켜고 껐다. 그런데 [gui/main_window.py](gui/main_window.py)는 세션 창을 여러 개
동시에 띄우는 게 설계 목표(갭 #10)라, 창 A가 복구 중일 때 창 B의 검사가 그 플래그를
그대로 물려받았다 — **부분 손상 파일이 "정상"으로, 반대 타이밍엔 부분 복구 가능한
파일이 "손상"으로** 나온다. 진단 정확도가 제품의 핵심 약속이라 기능 버그로 취급.

- 플래그를 만지는 모든 디코딩을 `analyzer.decode_mode()` 하나로 모으고 락으로
  직렬화했다. 검사 창이 하나뿐인 보통의 경우엔 경합이 없어 성능 차이가 없고,
  여러 창을 띄운 경우에만 디코딩이 순서대로 처리된다 — 그 경우는 지금까지
  애초에 틀린 결과가 나오던 상황이라 잃는 게 없다.
- 회귀 테스트: [tests/test_analyzer.py](tests/test_analyzer.py) 8~9번. **테스트가
  실제로 버그를 잡는지 확인함** — 수정을 되돌리면 "켜둔 상태=정상"으로 정확히
  실패하고, 수정하면 통과한다. 절단 비율이 중요해서(60%: 손상 허용 모드에서만
  읽히는 구간) 그 근거도 테스트 주석에 남겼다.

### 5-9. ✅ CLIP 입력이 원본 해상도로 디코딩되고 있었다 — GPU 이득을 가리던 진짜 병목(2026-09-11)

"고양이 찾기에 GPU가 실제로 얼마나 유의미한가"를 재보다 발견. CLIP은 224x224만
보는데 `core/photo_category.py`·`core/cat_finder.py`가 4032x3024를 통째로 디코딩한
뒤 224로 줄이고 있었다.

**실측(4032x3024, 디테일 많은 사진, 장당)**:

| 단계 | 시간 |
|---|---:|
| JPEG 디코드 + CLIP 전처리 | 128.9ms |
| CLIP 순전파 (GPU) | 4.9ms |
| CLIP 순전파 (CPU) | 61.8ms |

즉 **GPU가 줄여주는 57ms 앞에 129ms짜리 CPU 작업이 서 있었다** — 그래서 고양이
찾기의 GPU 이득이 1.4배로 눌려 있었고, "GPU가 필요하다"는 판단 자체가 이 병목
때문에 왜곡돼 있었다.

**조치**: `Image.draft("RGB", (224,224))`로 libjpeg가 1/8 스케일(504x378)로 바로
디코딩하게 했다. 두 파일이 같은 3줄을 쓰고 있어 `photo_category.load_image_for_clip()`
하나로 합쳤다(`core/torch_device.py`를 만들 때와 같은 이유).

- 디코드+전처리 **128.9ms → 25.4ms (5.1배**, 단색에 가까운 사진은 16배).
- `detect_cat()` 전체 **134ms → 31.5ms(GPU) / 94.3ms(CPU)**.
- 3만 장 기준: 예전 GPU 67분 → 지금 GPU 16분 / **CPU 47분**.
  → **CPU 전용으로 가도 예전 GPU 빌드보다 빠르다.** 5-1의 CUDA 제거 결정이
  속도를 희생하지 않는다는 근거가 이것.
- 판정이 바뀌지 않는지 검증: 같은 사진의 임베딩 **코사인 유사도 0.9996**
  (임계값 0.4/0.6에서 결과가 달라질 여지 없음).
  [tests/test_photo_category.py](tests/test_photo_category.py)에 회귀 테스트로
  고정 — 자산이 있을 때만 실행되고, 단색이 아니라 도형이 잔뜩 있는 폰카 크기
  사진으로 확인한다(단색은 축소해도 당연히 같아서 테스트가 의미 없음).

**한계/남은 것**: `draft()`는 JPEG 등 일부 형식에서만 동작하고 HEIC에는 같은
이득이 없다(다른 형식에서는 조용히 무시되므로 안전하다). 또 이 실측은 전부
합성 사진 기준이다 — 디코딩 비용은 해상도·JPEG 구조가 좌우하므로 실사진도
비슷할 것으로 보지만, 골드셋(P1)이 실사진으로 채워지면 같이 재확인할 것.

## 6. 지금 시점 종합 상태 (2026-09-11 기준, 네 번째 갱신 — 전체 코드 리뷰 반영)

**완료(✅)**:
- 1-2 디노이즈 안전장치, 1-3 얼굴복원 게이트+동물 제외.
- 5-1 onedir 전환 — 재빌드해서 실측까지 완료: **콜드 스타트 80초 → 4.2초**.
- 5-3 `reverse_geocoder`(LGPL) 제거 — `core/geocoder.py`를 자체 `scipy.cKDTree`
  구현으로 실제 교체, 테스트 0개였던 이 모듈에 `tests/test_geocoder.py` 신설(7개),
  `THIRD_PARTY_NOTICES.txt`에 GeoNames 데이터 저작자 표시 반영.
- 5-4 `PRIVACY_POLICY_DRAFT.md`, 5-3 `THIRD_PARTY_NOTICES.txt` 초안 작성.
- 5-5 원본 보호 버그 수정.
- **5-2 GPU 가속 실제 설치·실측까지 완료** — 처음엔 "Python 3.14는 공식 CUDA 휠이
  없다"고 잘못 판단했었는데(cu121/124만 확인한 탓), `cu126` 인덱스에서 정확히
  맞는 휠을 찾아 실제 설치했다. **다만 실측 결과가 기대만큼 좋지는 않았다** —
  작은 이미지에선 9.4배 빨라졌지만, 실제 폰카 해상도(12MP)에서는 1.7배에 그쳤다
  (아키텍처 특성으로 추정, 원인 심층 분석은 범위 밖).
- **5-7 배포 환경 전용 실패 경로 3종**(로그 위치 → 스토어 설치본에서 검사 멈춤,
  워커 4개 예외 미처리 → 모달 팝업 영구 잠김, UPX 압축) — 전체 코드 리뷰에서 발견,
  수정 완료.
- **5-8 진단 결과 오염 버그** — `LOAD_TRUNCATED_IMAGES` 전역 플래그를 여러 창이
  공유하던 문제, `analyzer.decode_mode()`로 직렬화. 회귀 테스트가 실제로 버그를
  잡는지(수정을 되돌리면 실패하는지) 확인까지 마침.
- 전부 실측/재현/테스트로 검증됨 — `tests/test_*.py` 전체 **230개 0 실패**
  (리뷰 수정분 회귀 테스트 10개 추가).

**설계/조사만 되고 실행은 미착수(⬜)**: 3(골드셋 — 기존 샘플이 전부 가짜였다는 것만
확인됨, 사용자가 실사진 제공하면 바로 채울 예정), 5-4의 나머지(연령등급/스크린샷/
지원연락처 — 실제 Partner Center 계정에서 처리해야 함), 5-6(옵트인 실패 로그 —
설계만 남음), GPU 가속이 해상도 클 때 왜 덜 빠른지 원인 분석(선택, 급하지 않음).

**리뷰에서 나왔지만 아직 손대지 않은 것**(구조 변경이라 별도 판단 필요):
- CI가 테스트를 전혀 안 돌린다 — `.github/workflows/build-macos.yml`이 유일한
  워크플로고 `claude/**` 푸시에만 동작. 게다가 그 워크플로가 만드는 `.app`에는
  AI 자산이 하나도 안 들어간다(`assets/*`가 전부 gitignore인데 `scripts/fetch_*`를
  실행하지 않음) — 받아서 실행하면 AI 기능이 통째로 빠진 빌드.
- 테스트가 pytest가 아니라 자체 `run()`+print 구조라 한 번에 돌릴 러너가 없고
  실패 지점의 stack trace가 안 나온다. 230개나 쌓인 지금이 옮길 시점.
- `gui/scan_session_window.py`가 화면 14개의 라우터 + 메서드 50개. Phase 2에서
  화면이 더 붙으면 여기가 먼저 무너진다.
- 2GB 패키지 — AI 복원 자산을 첫 사용 시 내려받는 선택 팩으로 분리하면 본체는
  100MB 미만. 스토어 제출 구조를 바꾸는 결정이라 제출 전에 정해야 한다.

**사용자가 해야 하는 것**: 골드셋용 실사진 제공(목록은 대화 참고), MS 스토어 실제
제출(Partner Center 계정 필요) — 이 둘은 제가 대신 못 한다.
