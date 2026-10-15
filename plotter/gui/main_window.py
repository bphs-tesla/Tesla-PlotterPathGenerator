"""메인 창: 카메라 미리보기, 촬영, 해칭 결과 확인, GRBL 전송."""

from __future__ import annotations

import contextlib
from pathlib import Path

import numpy as np
from PyQt6.QtCore import QSettings, Qt, QTimer
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from plotter import camera, gcode, grbl_sender, svg_export
from plotter.config import Config
from plotter.gui.preview import gray_to_qimage, render_lines
from plotter.gui.state import AppState, Controls, controls_for
from plotter.gui.workers import ConnectThread, ProcessThread, SendThread
from plotter.lines import Polyline

PREVIEW_SIZE = (480, 360)
FRAME_INTERVAL_MS = 33
READY_MESSAGE = "스페이스바나 촬영 버튼으로 촬영하세요"
RESULT_PLACEHOLDER = "촬영하면 해칭 결과가 여기에 표시됩니다"


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

        self._progress = QProgressBar()
        self._progress.setFormat("%v / %m 줄")
        self._progress.setValue(0)
        self._status = QLabel()

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

        layout = QVBoxLayout()
        layout.addLayout(camera_row)
        layout.addLayout(port_row)
        layout.addLayout(views)
        layout.addLayout(buttons)
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
        self._set_status("이미지 처리 중... (potrace, Inkscape, 해칭)")
        self._apply_state()
        self._worker = ProcessThread(gray, self._cfg, self)
        self._worker.succeeded.connect(self._on_processed)
        self._worker.failed.connect(self._on_process_failed)
        self._worker.start()

    def _on_processed(self, lines: list[Polyline]) -> None:
        width, height = self._image_size
        self._lines = lines
        self._commands = gcode.generate(lines, width, height, self._cfg)
        self._show_image(self._result_view, render_lines(lines, width, height))
        self._state = AppState.REVIEW
        try:
            svg_export.save_svg(lines, width, height, self._output_dir / "output.svg")
            gcode.save_gcode(self._commands, self._output_dir / "output.gcode")
        except OSError as exc:
            self._set_status(f"파일 저장 실패: {exc}")
        else:
            if lines:
                self._set_status(f"선 {len(lines)}개 생성, output.svg와 output.gcode 저장됨. 전송을 누르면 그리기 시작")
            else:
                self._set_status("그릴 선이 없습니다. 다시 촬영하세요")
        self._apply_state()

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
        self._worker = SendThread(self._sender, self._commands, self)
        self._worker.progress.connect(lambda done, total: self._progress.setValue(done))
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
        self._apply_state()

    def _on_send_failed(self, message: str) -> None:
        self._state = AppState.REVIEW
        self._disconnect()  # 다시 연결하면 GRBL 응답부터 다시 확인한다
        self._set_status(f"전송 실패: {message} (다시 연결하세요)")
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
