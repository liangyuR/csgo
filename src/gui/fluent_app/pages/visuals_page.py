# visuals_page.py
"""視覺設定頁面 - 顯示開關、偵測範圍"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import (
    SettingCardGroup, SwitchSettingCard, SettingCard,
    FluentIcon, BodyLabel
)
from ..components.slider_spin_card import SliderLabelCard

from ..base_page import BasePage
from ..language_manager import t


class VisualsPage(BasePage):
    """視覺設定頁面"""

    def __init__(self, parent=None):
        super().__init__("tab_display", parent)
        self._config = None
        self._initWidgets()
        self._initLayout()
        self._connectSignals()

    def setConfig(self, config):
        """設定 Config 實例並載入值"""
        self._config = config
        self._loadFromConfig()

    def _initWidgets(self):
        """初始化所有控制項"""

        # === 顯示設定 ===
        self.displayGroup = SettingCardGroup(t("tab_display"), self.scrollWidget)

        # 顯示 FOV
        self.showFovCard = SwitchSettingCard(
            FluentIcon.ZOOM,
            t("show_fov"),
            "",
            parent=self.displayGroup
        )

        # 顯示框體
        self.showBoxesCard = SwitchSettingCard(
            FluentIcon.CHECKBOX,
            t("show_boxes"),
            "",
            parent=self.displayGroup
        )

        # 顯示偵測信心值
        self.showConfidenceCard = SwitchSettingCard(
            FluentIcon.CERTIFICATE,
            t("show_confidence"),
            "",
            parent=self.displayGroup
        )

        # 顯示狀態面板
        self.showStatusCard = SwitchSettingCard(
            FluentIcon.INFO,
            t("show_status_panel"),
            "",
            parent=self.displayGroup
        )

        # 顯示 AI 偵測範圍
        self.showDetectRangeCard = SwitchSettingCard(
            FluentIcon.FULL_SCREEN,
            t("show_detect_range"),
            "",
            parent=self.displayGroup
        )

        # === 外觀設定 ===
        self.appearanceGroup = SettingCardGroup(t("appearance_options"), self.scrollWidget)

        # 啟用 Acrylic
        self.enableAcrylicCard = SwitchSettingCard(
            FluentIcon.LAYOUT,
            t("enable_acrylic"),
            "",
            parent=self.appearanceGroup
        )

        # 視窗磨砂透明度
        self.windowAlphaCard = SliderLabelCard(
            FluentIcon.BRUSH,
            t("acrylic_window_alpha"),
            0, 255,
            format_func=lambda v: str(v),
            description="",
            slider_width=200,
            parent=self.appearanceGroup
        )


    def _initLayout(self):
        """排版所有控制項"""
        # 顯示設定
        self.displayGroup.addSettingCard(self.showFovCard)
        self.displayGroup.addSettingCard(self.showBoxesCard)
        self.displayGroup.addSettingCard(self.showConfidenceCard)
        self.displayGroup.addSettingCard(self.showStatusCard)
        self.displayGroup.addSettingCard(self.showDetectRangeCard)
        self.addContent(self.displayGroup)

        # 外觀設定
        self.appearanceGroup.addSettingCard(self.enableAcrylicCard)
        self.appearanceGroup.addSettingCard(self.windowAlphaCard)

        self.addContent(self.appearanceGroup)

        self.scrollLayout.addStretch(1)

    def _connectSignals(self):
        """連接信號"""
        # 顯示設定
        self.showFovCard.checkedChanged.connect(self._onShowFovChanged)
        self.showBoxesCard.checkedChanged.connect(self._onShowBoxesChanged)
        self.showConfidenceCard.checkedChanged.connect(self._onShowConfidenceChanged)
        self.showStatusCard.checkedChanged.connect(self._onShowStatusChanged)
        self.showDetectRangeCard.checkedChanged.connect(self._onShowDetectRangeChanged)

        # 外觀設定
        self.enableAcrylicCard.checkedChanged.connect(self._onAcrylicEnabledChanged)
        self.windowAlphaCard.valueChanged.connect(self._onWindowAlphaChanged)


    def _loadFromConfig(self):
        """從 Config 載入值"""
        if not self._config:
            return

        # 顯示設定
        self.showFovCard.setChecked(self._config.show_fov)
        self.showBoxesCard.setChecked(self._config.show_boxes)
        self.showConfidenceCard.setChecked(self._config.show_confidence)
        self.showStatusCard.setChecked(self._config.show_status_panel)
        self.showDetectRangeCard.setChecked(self._config.show_detect_range)

        # 外觀設定
        self.enableAcrylicCard.setChecked(self._config.enable_acrylic)
        self.windowAlphaCard.setValue(self._config.acrylic_window_alpha)

    # === 回調函數 ===
    def _onShowFovChanged(self, checked):
        if self._config:
            self._config.show_fov = checked

    def _onShowBoxesChanged(self, checked):
        if self._config:
            self._config.show_boxes = checked

    def _onShowConfidenceChanged(self, checked):
        if self._config:
            self._config.show_confidence = checked

    def _onShowStatusChanged(self, checked):
        if self._config:
            self._config.show_status_panel = checked

    def _onShowDetectRangeChanged(self, checked):
        if self._config:
            self._config.show_detect_range = checked

    def _onAcrylicEnabledChanged(self, checked):
        if self._config:
            self._config.enable_acrylic = checked
            self._refreshWindowEffect()

    def _onWindowAlphaChanged(self, value):
        if self._config:
            self._config.acrylic_window_alpha = value
            self._refreshWindowEffect()



    def _refreshWindowEffect(self):
        """通知視窗刷新 Acrylic 效果與樣式"""
        window = self.window()
        if window:
            if hasattr(window, '_applyAcrylicEffect'):
                window._applyAcrylicEffect()
            if hasattr(window, '_applyThemeStyles'):
                window._applyThemeStyles()

    def retranslateUi(self):
        """刷新翻譯"""
        super().retranslateUi()

        # 群組標題
        self.displayGroup.titleLabel.setText(t("tab_display"))

        # 顯示設定
        self.showFovCard.titleLabel.setText(t("show_fov"))
        self.showBoxesCard.titleLabel.setText(t("show_boxes"))
        self.showConfidenceCard.titleLabel.setText(t("show_confidence"))
        self.showStatusCard.titleLabel.setText(t("show_status_panel"))
        self.showDetectRangeCard.titleLabel.setText(t("show_detect_range"))

        # 外觀設定
        self.appearanceGroup.titleLabel.setText(t("appearance_options"))
        self.enableAcrylicCard.titleLabel.setText(t("enable_acrylic"))
        self.windowAlphaCard.titleLabel.setText(t("acrylic_window_alpha"))
        self.windowAlphaCard.contentLabel.setText("")
