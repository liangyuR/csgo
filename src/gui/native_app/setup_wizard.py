"""Native PyQt6 first-run setup wizard."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .widgets import tr


class SetupWizard(QDialog):
    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Axiom Setup")
        self.resize(560, 360)

        self.stack = QStackedWidget(self)
        self.language_combo = QComboBox(self)
        self.dark_check = QCheckBox("Use dark mode", self)
        self.acrylic_check = QCheckBox("Enable acrylic effects", self)
        self.alpha_slider = QSlider(Qt.Orientation.Horizontal, self)

        self._build_pages()

        self.back_btn = QPushButton("Back", self)
        self.next_btn = QPushButton("Next", self)
        self.skip_btn = QPushButton("Skip", self)
        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        self.skip_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(self.skip_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.back_btn)
        buttons.addWidget(self.next_btn)

        root = QVBoxLayout(self)
        root.addWidget(self.stack, 1)
        root.addLayout(buttons)
        self._sync_buttons()

        self.setStyleSheet(
            """
            QLabel#heading { font-size: 22px; font-weight: 600; }
            QLabel#body { color: #555; }
            """
        )

    def _build_pages(self) -> None:
        self.stack.addWidget(self._language_page())
        self.stack.addWidget(self._theme_page())
        self.stack.addWidget(self._acrylic_page())

    def _language_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Language", page)
        heading.setObjectName("heading")
        body = QLabel("Choose the language used by saved runtime configuration.", page)
        body.setObjectName("body")
        body.setWordWrap(True)

        self.language_combo.clear()
        try:
            from core.language_manager import language_manager

            languages = language_manager.get_available_languages()
            self.language_combo.addItems(languages)
            current = language_manager.get_current_language()
            idx = self.language_combo.findText(current)
            if idx >= 0:
                self.language_combo.setCurrentIndex(idx)
        except Exception:
            self.language_combo.addItem("English_English")

        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(self.language_combo)
        layout.addStretch(1)
        return page

    def _theme_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Theme", page)
        heading.setObjectName("heading")
        body = QLabel("Use a plain native Qt theme for the lightweight settings UI.", page)
        body.setObjectName("body")
        body.setWordWrap(True)

        self.dark_check.setChecked(bool(getattr(self.config, "dark_mode", False)))
        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(self.dark_check)
        layout.addStretch(1)
        return page

    def _acrylic_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        heading = QLabel("Effects", page)
        heading.setObjectName("heading")
        body = QLabel("Acrylic stays optional and is only applied where the existing Win32 helpers support it.", page)
        body.setObjectName("body")
        body.setWordWrap(True)

        self.acrylic_check.setChecked(bool(getattr(self.config, "enable_acrylic", True)))
        self.alpha_slider.setRange(0, 255)
        self.alpha_slider.setValue(int(getattr(self.config, "acrylic_window_alpha", 187)))

        layout.addWidget(heading)
        layout.addWidget(body)
        layout.addWidget(self.acrylic_check)
        layout.addWidget(QLabel("Window alpha", page))
        layout.addWidget(self.alpha_slider)
        layout.addStretch(1)
        return page

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._sync_buttons()

    def _next(self) -> None:
        if self.stack.currentIndex() >= self.stack.count() - 1:
            self._apply()
            self.accept()
            return
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.back_btn.setEnabled(self.stack.currentIndex() > 0)
        self.next_btn.setText("Finish" if self.stack.currentIndex() == self.stack.count() - 1 else "Next")

    def _apply(self) -> None:
        self.config.dark_mode = self.dark_check.isChecked()
        self.config.enable_acrylic = self.acrylic_check.isChecked()
        self.config.acrylic_window_alpha = self.alpha_slider.value()

        try:
            from core.language_manager import language_manager

            language_manager.set_language(self.language_combo.currentText())
        except Exception:
            pass

    def applyChosenTheme(self) -> None:
        self._apply()
