"""메인 창: 카메라 미리보기, 촬영, 해칭 결과 확인, GRBL 전송."""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from plotter import camera, gcode, grbl_sender, svg_export
from plotter.config import Config
from plotter.gui.preview import gray_to_qimage, render_lines
from plotter.gui.state import AppState, Controls, controls_for
from plotter.gui.workers import ConnectThread, ProcessThread, SendThread
from plotter.lines import Polyline
from plotter.maze import MIN_CELLS, Difficulty, generate_maze, maze_drawing

PREVIEW_SIZE = (480, 360)
FRAME_INTERVAL_MS = 33
READY_MESSAGE = "스페이스바나 촬영 버튼으로 촬영하세요"
RESULT_PLACEHOLDER = "촬영하면 해칭 결과가 여기에 표시됩니다"
MAX_MAZE_CELLS = 60
JOG_STEPS_MM = (1.0, 10.0, 50.0)


class MainWindow(QMainWindow):
    def __init__(self, cfg: Config, output_dir: Path, settings: QSettings | None = None):
        super().__init__()
        self.setWindowTitle("Plotter Path Generator")
        self._cfg = cfg
        self._output_dir = output_dir
        self._settings = settings or QSettings("TeslaPlotter", "PlotterPathGenerator")

        self._state = AppState.LIVE
        self._capture = None
        self._last_gray: np.ndarray | None = None
        self._image_size = (0, 0)
        self._lines: list[Polyline] = []
        self._commands: list[str] = []
        self._serial = None
        self._sender: grbl_sender.GrblSender | None = None
        self._worker = None
        self._connect_worker: ConnectThread | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_camera_frame)

        self._build_ui()
        self._refresh_ports()
        self._refresh_cameras()
        self._apply_state()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        self._camera_combo = QComboBox()
        self._camera_combo.currentIndexChanged.connect(self._open_selected_camera)
        self._camera_refresh = self._button("새로고침", self._refresh_cameras)

        self._port_combo = QComboBox()
        self._port_refresh = self._button("새로고침", self._refresh_ports)
        self._connect_button = self._button("연결", self._toggle_connection)
        self._connection_label = QLabel()

        self._camera_view = self._view("카메라 준비 중")
        self._result_view = self._view(RESULT_PLACEHOLDER)

        self._capture_button = self._button("촬영 (Space)", self._capture_frame)
        self._retake_button = self._button("다시 촬영", self._retake)
        self._send_button = self._button("전송", self._send)
        self._pause_button = self._button("일시정지", self._toggle_pause)
        self._stop_button = self._button("정지", self._stop)

        # 미로 크기 기본값 24×20칸은 작업 영역 300×250mm와 같은 비율이다
        self._maze_cols = self._cell_count(24)
        self._maze_rows = self._cell_count(20)
        self._maze_difficulty = QComboBox()
        self._maze_difficulty.addItems([d.value for d in Difficulty])
        self._maze_difficulty.setCurrentText(Difficulty.NORMAL.value)
        self._maze_difficulty.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._maze_button = self._button("미로 생성", self._make_maze)

        # 끝으로 이동: 아두이노에 저장된 작업 영역의 각 끝으로 펜을 옮긴다 (다른 축은 그대로)
        self._move_buttons = [
            self._button("← 왼쪽 끝으로", lambda: self._move_to_edge("ML", "왼쪽 끝")),
            self._button("→ 오른쪽 끝으로", lambda: self._move_to_edge("MR", "오른쪽 끝")),
            self._button("↓ 아래 끝으로", lambda: self._move_to_edge("MB", "아래 끝")),
            self._button("↑ 위 끝으로", lambda: self._move_to_edge("MT", "위 끝")),
        ]
        # 끝 설정: 펜을 각 끝으로 옮긴 뒤 누른다. 왼쪽/아래 끝이 원점, 오른쪽/위 끝이 작업 영역 크기
        self._edge_buttons = [
            self._button("X 왼쪽 끝", lambda: self._set_edge("EL", "왼쪽 끝 (X=0)")),
            self._button("X 오른쪽 끝", lambda: self._set_edge("ER", "오른쪽 끝")),
            self._button("Y 아래 끝", lambda: self._set_edge("EB", "아래 끝 (Y=0)")),
            self._button("Y 위 끝", lambda: self._set_edge("ET", "위 끝")),
        ]
        # 끝 설정 모드: 체크했을 때만 조그 버튼과 끝 설정 버튼을 보여 준다
        self._edge_mode = QCheckBox("끝 설정 모드")
        self._edge_mode.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._edge_mode.toggled.connect(self._toggle_edge_mode)
        self._jog_step = QComboBox()
        for mm in JOG_STEPS_MM:
            self._jog_step.addItem(f"{mm:g} mm", mm)
        self._jog_step.setCurrentIndex(1)
        self._jog_step.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._jog_buttons = [
            self._button("← X-", lambda: self._jog(-1, 0)),
            self._button("→ X+", lambda: self._jog(1, 0)),
            self._button("↓ Y-", lambda: self._jog(0, -1)),
            self._button("↑ Y+", lambda: self._jog(0, 1)),
        ]

        # 아두이노 설정: 최고 속도와 펜 서보 각도. 연결하면 아두이노에 저장된 값으로 채워진다
        self._speed = self._setting_box(10, 3000, 150, " mm/분", step=10)
        self._pen_up_angle = self._setting_box(0, 180, 45, "°")
        self._pen_down_angle = self._setting_box(0, 180, 90, "°")
        self._apply_settings_button = self._button("설정 적용", self._apply_machine_settings)
        self._pen_buttons = [
            self._button("펜 올리기", lambda: self._run_machine(["M5"], "펜 올리는 중...", "펜을 올렸습니다")),
            self._button("펜 내리기", lambda: self._run_machine(["M3"], "펜 내리는 중...", "펜을 내렸습니다")),
        ]

        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m 줄")
        self._progress.setValue(0)
        self._status = QLabel()
        # 아두이노에 저장된 작업 영역과 현재 위치. 연결할 때와 이동 / 끝 설정 / 그리기 뒤에 갱신한다
        self._machine_label = QLabel()
        self._machine_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._show_machine_info(None)

        camera_row = QHBoxLayout()
        camera_row.addWidget(QLabel("카메라:"))
        camera_row.addWidget(self._camera_combo, 1)
        camera_row.addWidget(self._camera_refresh)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("포트:"))
        port_row.addWidget(self._port_combo, 1)
        port_row.addWidget(self._port_refresh)
        port_row.addWidget(self._connect_button)
        port_row.addWidget(self._connection_label)

        views = QHBoxLayout()
        views.addWidget(self._camera_view)
        views.addWidget(self._result_view)

        buttons = QHBoxLayout()
        for button in (self._capture_button, self._retake_button, self._send_button,
                       self._pause_button, self._stop_button):
            buttons.addWidget(button)

        maze_row = QHBoxLayout()
        maze_row.addWidget(QLabel("미로:"))
        maze_row.addWidget(QLabel("가로"))
        maze_row.addWidget(self._maze_cols)
        maze_row.addWidget(QLabel("세로"))
        maze_row.addWidget(self._maze_rows)
        maze_row.addWidget(QLabel("칸"))
        maze_row.addWidget(QLabel("난이도"))
        maze_row.addWidget(self._maze_difficulty)
        maze_row.addWidget(self._maze_button)
        maze_row.addStretch(1)

        move_row = QHBoxLayout()
        move_row.addWidget(QLabel("이동:"))
        for button in self._move_buttons:
            move_row.addWidget(button)
        move_row.addStretch(1)
        move_row.addWidget(self._edge_mode)

        jog_row = QHBoxLayout()
        jog_row.addWidget(QLabel("조그:"))
        jog_row.addWidget(self._jog_step)
        for button in self._jog_buttons:
            jog_row.addWidget(button)
        jog_row.addStretch(1)

        edge_row = QHBoxLayout()
        edge_row.addWidget(QLabel("끝 설정:"))
        for button in self._edge_buttons:
            edge_row.addWidget(button)
        edge_row.addStretch(1)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("속도:"))
        settings_row.addWidget(self._speed)
        settings_row.addWidget(QLabel("펜 올림 각도"))
        settings_row.addWidget(self._pen_up_angle)
        settings_row.addWidget(QLabel("펜 내림 각도"))
        settings_row.addWidget(self._pen_down_angle)
        settings_row.addWidget(self._apply_settings_button)
        for button in self._pen_buttons:
            settings_row.addWidget(button)
        settings_row.addStretch(1)

        edge_layout = QVBoxLayout()
        edge_layout.setContentsMargins(0, 0, 0, 0)
        edge_layout.addLayout(jog_row)
        edge_layout.addLayout(edge_row)
        self._edge_panel = QWidget()
        self._edge_panel.setLayout(edge_layout)
        self._edge_panel.setVisible(False)

        layout = QVBoxLayout()
        layout.addLayout(camera_row)
        layout.addLayout(port_row)
        layout.addLayout(move_row)
        layout.addWidget(self._machine_label)
        layout.addLayout(settings_row)
        layout.addWidget(self._edge_panel)
        layout.addLayout(views)
        layout.addLayout(buttons)
        layout.addLayout(maze_row)
        layout.addWidget(self._progress)
        layout.addWidget(self._status)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Space"), self, activated=self._capture_frame)

    def _button(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        # 버튼이 포커스를 가지면 스페이스바가 그 버튼을 누르므로 포커스를 받지 않게 한다
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(slot)
        return button

    def _cell_count(self, value: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(MIN_CELLS, MAX_MAZE_CELLS)
        box.setValue(value)
        # 클릭했을 때만 포커스를 받아, 평소에는 스페이스바가 촬영 단축키로 동작하게 한다
        box.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        return box

    def _setting_box(self, low: int, high: int, value: int, suffix: str, step: int = 1) -> QSpinBox:
        box = QSpinBox()
        box.setRange(low, high)
        box.setSingleStep(step)
        box.setValue(value)
        box.setSuffix(suffix)
        box.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        return box

    def _view(self, placeholder: str) -> QLabel:
        label = QLabel(placeholder)
        label.setFixedSize(*PREVIEW_SIZE)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("border: 1px solid #888; background: #f4f4f4;")
        return label

    def _show_image(self, label: QLabel, image: QImage) -> None:
        label.setPixmap(QPixmap.fromImage(image).scaled(
            label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _set_status(self, message: str) -> None:
        self._status.setText(message)

    def _controls(self) -> Controls:
        return controls_for(
            self._state,
            camera_ready=self._capture is not None,
            port_connected=self._serial is not None,
            has_lines=bool(self._lines),
        )

    def _apply_state(self) -> None:
        c = self._controls()
        connected = self._serial is not None
        self._camera_combo.setEnabled(c.select_camera)
        self._camera_refresh.setEnabled(c.select_camera)
        connecting = self._connecting()
        self._port_combo.setEnabled(c.select_port and not connected and not connecting)
        self._port_refresh.setEnabled(c.select_port and not connected and not connecting)
        self._connect_button.setEnabled(c.select_port and not connecting)
        self._connect_button.setText("연결 해제" if connected else "연결")
        self._connection_label.setText("● 연결됨" if connected else "● 연결 안 됨")
        self._capture_button.setEnabled(c.capture)
        self._retake_button.setEnabled(c.retake)
        self._send_button.setEnabled(c.send)
        self._pause_button.setEnabled(c.pause or c.resume)
        self._pause_button.setText("재개" if c.resume else "일시정지")
        self._stop_button.setEnabled(c.stop)
        self._maze_button.setEnabled(c.maze)
        self._maze_cols.setEnabled(c.maze)
        self._maze_rows.setEnabled(c.maze)
        self._maze_difficulty.setEnabled(c.maze)
        # 이동과 끝 설정은 연결되어 있고 그리는 중이 아닐 때만
        machine = c.select_port and connected and not connecting
        self._jog_step.setEnabled(machine)
        for widget in (*self._move_buttons, *self._jog_buttons, *self._edge_buttons, *self._pen_buttons,
                       self._speed, self._pen_up_angle, self._pen_down_angle, self._apply_settings_button):
            widget.setEnabled(machine)

    # ---------- 카메라 ----------

    def _refresh_cameras(self) -> None:
        if self._state is not AppState.LIVE:
            return
        self._close_camera()
        indices = camera.list_cameras()
        self._camera_combo.blockSignals(True)
        self._camera_combo.clear()
        for index in indices:
            self._camera_combo.addItem(f"카메라 {index}", index)
        saved = self._settings.value("camera_index", -1, type=int)
        position = self._camera_combo.findData(saved)
        self._camera_combo.setCurrentIndex(position if position >= 0 else 0)
        self._camera_combo.blockSignals(False)
        if not indices:
            self._camera_view.setText("카메라 없음")
            self._set_status("카메라를 찾을 수 없습니다. 연결한 뒤 새로고침을 누르세요")
            self._apply_state()
            return
        self._open_selected_camera()

    def _open_selected_camera(self) -> None:
        index = self._camera_combo.currentData()
        if index is None:
            return
        self._close_camera()
        try:
            self._capture = camera.open_camera(index)
        except camera.CameraError as exc:
            self._set_status(str(exc))
            self._apply_state()
            return
        self._settings.setValue("camera_index", index)
        self._timer.start(FRAME_INTERVAL_MS)
        self._set_status(READY_MESSAGE)
        self._apply_state()

    def _close_camera(self) -> None:
        self._timer.stop()
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self._last_gray = None

    def _update_camera_frame(self) -> None:
        if self._capture is None:
            return
        gray = camera.read_gray(self._capture)
        if gray is None:
            return
        self._last_gray = gray
        self._show_image(self._camera_view, gray_to_qimage(gray))

    # ---------- 촬영과 처리 ----------

    def _capture_frame(self) -> None:
        if not self._controls().capture or self._last_gray is None:
            return
        self._timer.stop()  # 촬영한 프레임이 미리보기에 남아 있게 한다
        gray = self._last_gray.copy()
        self._image_size = (gray.shape[1], gray.shape[0])
        self._state = AppState.PROCESSING
        self._set_status("이미지 처리 중... (potrace, 해칭)")
        self._apply_state()
        self._worker = ProcessThread(gray, self._cfg, self)
        self._worker.succeeded.connect(self._on_processed)
        self._worker.failed.connect(self._on_process_failed)
        self._worker.start()

    def _make_maze(self) -> None:
        """미로를 만들어 촬영 결과와 똑같이 미리보기, 저장, 전송할 수 있게 한다."""
        if not self._controls().maze:
            return
        cols, rows = self._maze_cols.value(), self._maze_rows.value()
        difficulty = Difficulty(self._maze_difficulty.currentText())
        self._timer.stop()  # 결과 확인 중에는 카메라 미리보기를 멈춘다
        # 벽과 입구/출구 화살표. 화살표가 들어갈 여백만큼 그림이 커진다
        lines, width, height = maze_drawing(generate_maze(cols, rows, difficulty=difficulty))
        self._image_size = (width, height)
        self._on_processed(lines, label=f"미로 {cols}×{rows}칸 ({difficulty.value}), ")

    def _on_processed(self, lines: list[Polyline], label: str = "") -> None:
        width, height = self._image_size
        self._lines = lines
        self._commands = gcode.generate(lines, width, height, self._cfg)
        self._show_image(self._result_view, render_lines(lines, width, height))
        self._state = AppState.REVIEW
        # 촬영할 때마다 시각을 붙인 새 파일로 저장해 이전 결과를 덮어쓰지 않는다
        stem = f"output-{self._timestamp()}"
        svg_path = self._output_dir / f"{stem}.svg"
        gcode_path = self._output_dir / f"{stem}.gcode"
        try:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            svg_export.save_svg(lines, width, height, svg_path)
            gcode.save_gcode(self._commands, gcode_path)
        except OSError as exc:
            self._set_status(f"파일 저장 실패: {exc}")
        else:
            if lines:
                self._set_status(
                    f"{label}선 {len(lines)}개 생성, {self._output_dir.name}/{svg_path.name}, "
                    f"{gcode_path.name} 저장됨. 전송을 누르면 그리기 시작")
            else:
                self._set_status("그릴 선이 없습니다. 다시 촬영하세요")
        self._apply_state()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def _on_process_failed(self, message: str) -> None:
        self._retake()
        self._set_status(f"처리 실패: {message}")

    def _retake(self) -> None:
        self._lines = []
        self._commands = []
        self._result_view.clear()
        self._result_view.setText(RESULT_PLACEHOLDER)
        self._progress.setValue(0)
        self._state = AppState.LIVE
        if self._capture is not None:
            self._timer.start(FRAME_INTERVAL_MS)
            self._set_status(READY_MESSAGE)
        self._apply_state()

    # ---------- 시리얼 ----------

    def _refresh_ports(self) -> None:
        current = self._port_combo.currentText() or self._settings.value("port", "", type=str)
        ports = grbl_sender.available_ports()
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)
        self._apply_state()

    def _toggle_connection(self) -> None:
        if self._serial is not None:
            self._disconnect()
            self._set_status("연결을 해제했습니다")
            return
        name = self._port_combo.currentText()
        if not name:
            self._set_status("시리얼 포트를 선택하세요")
            return
        self._set_status(f"{name}에 연결 중... (GRBL 응답을 최대 몇 초 기다립니다)")
        self._connect_worker = ConnectThread(name, self._cfg.baud, self)
        self._connect_worker.connected.connect(lambda port: self._on_connected(name, port))
        self._connect_worker.failed.connect(self._on_connect_failed)
        self._connect_worker.finished.connect(self._on_connect_finished)
        self._apply_state()
        self._connect_worker.start()

    def _connecting(self) -> bool:
        return self._connect_worker is not None and not self._connect_worker.isFinished()

    def _on_connected(self, name: str, port) -> None:
        self._serial = port
        self._sender = grbl_sender.GrblSender(self._serial, self._cfg.pen_up)
        self._settings.setValue("port", name)
        self._set_status(f"{name}에 연결됨")
        self._show_machine_info(self._connect_worker.info if self._connect_worker is not None else None)
        self._apply_state()

    def _on_connect_failed(self, message: str) -> None:
        self._set_status(message)
        self._apply_state()

    def _on_connect_finished(self) -> None:
        self._apply_state()

    def _disconnect(self) -> None:
        if self._serial is not None:
            with contextlib.suppress(Exception):
                self._serial.close()
        self._serial = None
        self._sender = None
        self._show_machine_info(None)
        self._apply_state()

    # ---------- 전송 ----------

    def _send(self) -> None:
        if not self._controls().send or self._sender is None:
            return
        self._progress.setRange(0, len(self._commands))
        self._progress.setValue(0)
        self._state = AppState.SENDING
        self._set_status("그리는 중...")
        self._apply_state()
        # 다 그린 뒤 $L로 현재 위치를 다시 읽는다 (진행 막대는 그림 줄 수까지만)
        self._worker = SendThread(self._sender, [*self._commands, "$L"], self)
        self._worker.progress.connect(lambda done, total: self._progress.setValue(min(done, len(self._commands))))
        self._worker.completed.connect(self._on_send_completed)
        self._worker.failed.connect(self._on_send_failed)
        self._worker.start()

    def _toggle_pause(self) -> None:
        if self._sender is None:
            return
        try:
            if self._state is AppState.SENDING:
                self._sender.pause()
                self._state = AppState.PAUSED
                self._set_status("일시정지됨")
            elif self._state is AppState.PAUSED:
                self._sender.resume()
                self._state = AppState.SENDING
                self._set_status("그리는 중...")
        except grbl_sender.GrblError as exc:
            self._set_status(str(exc))  # 전송 스레드도 같은 오류로 끝나며 _on_send_failed가 정리한다
            return
        self._apply_state()

    def _stop(self) -> None:
        if self._sender is None or self._state not in (AppState.SENDING, AppState.PAUSED):
            return
        self._sender.request_stop()
        self._stop_button.setEnabled(False)
        self._pause_button.setEnabled(False)
        self._set_status("정지하는 중... (펜을 올립니다)")

    def _on_send_completed(self, finished: bool) -> None:
        self._state = AppState.REVIEW
        self._set_status("그리기 완료" if finished else "정지했습니다. 펜을 올렸습니다")
        self._update_machine_info()
        self._apply_state()

    def _on_send_failed(self, message: str) -> None:
        self._state = AppState.REVIEW
        self._set_status(f"전송 실패: {message}{self._after_failure()}")
        self._apply_state()

    def _after_failure(self) -> str:
        """실패한 뒤 연결을 정리하고, 상태 줄에 덧붙일 안내를 돌려준다."""
        if isinstance(getattr(self._worker, "error", None), grbl_sender.GrblReplyError):
            # 아두이노가 명령만 거부했다. 다시 연결하면 아두이노가 재부팅되어 원점을 잃으므로 연결을 유지한다
            return ""
        self._disconnect()  # 다시 연결하면 GRBL 응답부터 다시 확인한다
        return " (다시 연결하세요)"

    # ---------- 끝 이동 / 끝 설정 ----------

    def _toggle_edge_mode(self, on: bool) -> None:
        self._edge_panel.setVisible(on)
        if on:
            self._set_status("조그로 펜을 각 끝까지 옮긴 뒤 해당 끝 설정 버튼을 누르세요")

    def _jog(self, dx: int, dy: int) -> None:
        step = self._jog_step.currentData()
        # $J=는 작업 영역 제한을 무시하므로 지금 영역 밖으로도 옮길 수 있다
        self._run_machine([f"$J=G91 G0 X{dx * step:g} Y{dy * step:g}"], "이동 중...", "이동했습니다")

    def _move_to_edge(self, command: str, name: str) -> None:
        self._run_machine([f"${command}"], f"{name}으로 이동 중...", f"{name}으로 이동했습니다")

    def _set_edge(self, command: str, name: str) -> None:
        # 새 작업 영역은 설정값 줄에 나온다
        self._run_machine([f"${command}"], f"{name} 기록 중...", f"{name}을(를) 설정했습니다")

    def _apply_machine_settings(self) -> None:
        # 아두이노가 EEPROM에 저장하므로 다시 켜도 유지된다. 지금 펜 상태의 각도는 바로 그 각도로 움직인다
        commands = [
            f"$V={self._speed.value()}",
            f"$PU={self._pen_up_angle.value()}",
            f"$PD={self._pen_down_angle.value()}",
        ]
        self._run_machine(commands, "설정 적용 중...", "설정을 적용했습니다")

    def _run_machine(self, commands: list[str], busy: str, done: str) -> None:
        """그림이 아닌 짧은 명령을 보낸다. 끝나면 원래 화면 상태로 돌아간다."""
        if self._sender is None or self._state in (AppState.SENDING, AppState.PAUSED):
            return
        previous = self._state
        self._state = AppState.SENDING
        self._set_status(busy)
        self._apply_state()
        # 끝에 $L을 붙여 작업 영역과 현재 위치를 다시 읽는다
        self._worker = SendThread(self._sender, [*commands, "$L"], self)
        self._worker.completed.connect(lambda finished: self._on_machine_done(previous, done if finished else "정지했습니다"))
        self._worker.failed.connect(lambda message: self._on_machine_failed(previous, message))
        self._worker.start()

    def _on_machine_done(self, previous: AppState, message: str) -> None:
        self._state = previous
        if self._sender is not None:
            # 설정값이 아닌 메시지(예: 끝이 기록되지 않음)는 상태 줄에 붙여 보여 준다
            notes = [m for m in self._sender.messages if grbl_sender.parse_machine_info(m) is None]
            if notes:
                message = f"{message} {notes[-1]}"
        self._set_status(message)
        self._update_machine_info()
        self._apply_state()

    def _update_machine_info(self) -> None:
        """마지막 전송에서 받은 $L 응답으로 설정값 줄을 갱신한다."""
        if self._sender is None:
            return
        info = grbl_sender.latest_machine_info(self._sender.messages)
        if info is not None:
            self._show_machine_info(info)

    def _show_machine_info(self, info: grbl_sender.MachineInfo | None) -> None:
        if info is None:
            text = "아두이노 설정값: -" if self._serial is None else "아두이노 설정값: 읽지 못함 (펌웨어를 새로 올리세요)"
            self._machine_label.setText(text)
            self._machine_label.setStyleSheet("")
            return
        parts = [f"아두이노 작업 영역: X 0 ~ {info.width_mm:.2f} mm, Y 0 ~ {info.height_mm:.2f} mm"]
        if info.x_mm is not None and info.y_mm is not None:
            parts.append(f"현재 위치: X {info.x_mm:.2f}, Y {info.y_mm:.2f}")
        if not info.limits_on:
            parts.append("영역 제한 꺼짐")
        # 설정 입력칸을 아두이노에 저장된 값으로 맞춘다
        if info.speed_mm_min is not None:
            self._speed.setValue(round(info.speed_mm_min))
        if info.pen_up_deg is not None and info.pen_down_deg is not None:
            self._pen_up_angle.setValue(info.pen_up_deg)
            self._pen_down_angle.setValue(info.pen_down_deg)
        width, height = self._cfg.work_width_mm, self._cfg.work_height_mm
        # 원점 이동이 스텝(1/80 mm) 단위라 아주 작은 차이는 무시한다
        mismatch = abs(info.width_mm - width) > 0.05 or abs(info.height_mm - height) > 0.05
        if mismatch:
            parts.append(f"⚠ G-code는 {width:g} × {height:g} mm 기준 (config.toml) → 영역 밖 오류(15)가 날 수 있음")
        self._machine_label.setText("  |  ".join(parts))
        self._machine_label.setStyleSheet("color: #c0392b;" if mismatch else "")

    def _on_machine_failed(self, previous: AppState, message: str) -> None:
        self._state = previous
        self._set_status(f"명령 실패: {message}{self._after_failure()}")
        self._apply_state()

    # ---------- 종료 ----------

    def closeEvent(self, event) -> None:
        if self._state in (AppState.SENDING, AppState.PAUSED):
            answer = QMessageBox.question(self, "그리는 중", "그리기를 정지하고 종료할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._sender.request_stop()
        if self._worker is not None:
            self._worker.wait()
        if self._connect_worker is not None:
            self._connect_worker.wait()
            # 연결이 끝났지만 시그널이 처리되기 전에 창을 닫으면 포트가 열린 채 남는다
            if self._connect_worker.port is not None and self._connect_worker.port is not self._serial:
                with contextlib.suppress(Exception):
                    self._connect_worker.port.close()
        self._close_camera()
        self._disconnect()
        event.accept()
