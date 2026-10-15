"""플로터 GUI 실행."""

import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QMessageBox

from plotter.config import ConfigError, load_config
from plotter.gui.main_window import MainWindow

ROOT = Path(__file__).parent


def main() -> int:
    app = QApplication(sys.argv)
    try:
        cfg = load_config(ROOT / "config.toml")
    except ConfigError as exc:
        QMessageBox.critical(None, "설정 오류", f"config.toml을 읽을 수 없습니다.\n\n{exc}")
        return 1
    window = MainWindow(cfg, ROOT)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
