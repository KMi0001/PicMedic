"""
core/torch_device.py

AI 모델(디블러/디노이즈/얼굴복원/사진분류/고양이찾기/사진진단 얼굴탐지)이 공통으로
쓰는 디바이스 판정 로직. 원래 6개 파일에 `torch.device("cuda" if torch.cuda.is_available()
else "cpu")`가 그대로 중복돼 있었는데, macOS엔 CUDA가 없어서 Apple Silicon GPU(MPS)를
전혀 못 쓰고 있었다(2026-09-11, 유료화 준비 검토 중 발견). CLAUDE.md 크로스플랫폼 원칙상
OS 분기를 늘리는 대신, 판정 순서(cuda → mps → cpu)를 여기 한 곳에서만 관리한다.

torch는 지연 import — 각 호출부와 동일한 이유(앱 시작 속도, torch 미설치 환경에서도
이 모듈 자체의 import는 안전해야 함).
"""

from __future__ import annotations


def resolve_device():
    """사용 가능한 최선의 torch 디바이스를 반환한다: CUDA(NVIDIA) → MPS(Apple
    Silicon) → CPU 순."""
    import torch

    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
