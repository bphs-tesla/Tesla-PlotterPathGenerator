"""화면 상태별로 어떤 버튼을 누를 수 있는지 정한다."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class AppState(Enum):
    LIVE = auto()        # 카메라 미리보기, 촬영 대기
    PROCESSING = auto()  # 이미지 처리 중
    REVIEW = auto()      # 결과 확인, 전송 대기
    SENDING = auto()     # 그리는 중
    PAUSED = auto()      # 그리기 일시정지


@dataclass(frozen=True)
class Controls:
    select_camera: bool
    select_port: bool
    capture: bool
    retake: bool
    send: bool
    pause: bool
    resume: bool
    stop: bool


def controls_for(state: AppState, *, camera_ready: bool, port_connected: bool, has_lines: bool) -> Controls:
    drawing = state in (AppState.SENDING, AppState.PAUSED)
    return Controls(
        select_camera=state is AppState.LIVE,
        select_port=not drawing,
        capture=state is AppState.LIVE and camera_ready,
        retake=state is AppState.REVIEW,
        send=state is AppState.REVIEW and port_connected and has_lines,
        pause=state is AppState.SENDING,
        resume=state is AppState.PAUSED,
        stop=drawing,
    )
