# aim_page.py
"""瞄準輔助頁面 - 模型設定、PID、貝塞爾曲線、智慧追蹤"""

import os
import math
import threading
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QMessageBox, QStackedWidget
from PyQt6.QtGui import QDesktopServices
from qfluentwidgets import (
    SettingCardGroup, ComboBoxSettingCard, SwitchSettingCard,
    PushSettingCard, RangeSettingCard, OptionsSettingCard,
    FluentIcon,
    BodyLabel, ComboBox, PrimaryPushButton, SettingCard,
    qconfig, ConfigItem, OptionsConfigItem, RangeConfigItem,
    BoolValidator, OptionsValidator, RangeValidator, PushButton,
    SegmentedWidget
)
from ..components.no_wheel_widgets import NoWheelSlider as Slider, NoWheelSpinBox as SpinBox, NoWheelDoubleSpinBox as DoubleSpinBox
from ..components.slider_spin_card import SliderSpinCard, SliderLabelCard

from ..base_page import BasePage
from ..language_manager import t
from core.config import apply_model_constraints
from core.model_registry import get_model_spec, list_model_specs


class AimPage(BasePage):
    """瞄準輔助設定頁面"""

    def __init__(self, parent=None):
        super().__init__("tab_aim_control", parent)
        self._config = None
        self._initWidgets()
        self._initLayout()
        self._connectSignals()

    def setConfig(self, config):
        """設定 Config 實例並載入值"""
        self._config = config
        self._loadFromConfig()

    def _currentModelSpec(self):
        if not self._config:
            return None
        return get_model_spec(getattr(self._config, "model_id", ""))

    def _updateModelConstraintControls(self):
        if not self._config:
            return

        apply_model_constraints(self._config)
        spec = self._currentModelSpec()
        max_h = max(1080, self._config.height)

        if spec and getattr(spec, "lock_detect_range_to_input", False):
            self.fovCard.setRange(50, max(50, spec.input_size))
            self.detectRangeCard.setRange(spec.input_size, spec.input_size)
            self.detectRangeCard.setControlsEnabled(False)
            self.detectRangeCard.setDescription(f"{t('detect_range_note')} ({spec.input_size}x{spec.input_size})")
        else:
            self.fovCard.setRange(50, 500)
            self.detectRangeCard.setRange(100, max_h)
            self.detectRangeCard.setControlsEnabled(True)
            self.detectRangeCard.setDescription(t("detect_range_note"))

    def _initWidgets(self):
        """初始化所有控制項"""

        # === 模型設定 ===
        self.modelGroup = SettingCardGroup(t("model_settings"), self.scrollWidget)

        # 模型選擇
        self.modelCombo = ComboBox()
        self.modelCombo.setMinimumWidth(200)
        # 注意：不在這裡調用 _refreshModelList()，等 setConfig 時再載入
        self.modelCard = SettingCard(
            FluentIcon.ROBOT,
            t("model"),
            "",
            self.modelGroup
        )
        self.modelCard.hBoxLayout.addWidget(self.modelCombo, 0, Qt.AlignmentFlag.AlignRight)
        self.modelCard.hBoxLayout.addSpacing(16)

        self.activeClassCombo = ComboBox()
        self.activeClassCombo.setMinimumWidth(120)
        self.activeClassCard = SettingCard(
            FluentIcon.TILES,
            t("active_target_class"),
            "",
            self.modelGroup
        )
        self.activeClassCard.hBoxLayout.addWidget(self.activeClassCombo, 0, Qt.AlignmentFlag.AlignRight)
        self.activeClassCard.hBoxLayout.addSpacing(16)

        # 開啟模型資料夾
        self.openModelFolderBtn = PrimaryPushButton(t("open_model_folder"))
        self.openModelFolderCard = SettingCard(
            FluentIcon.FOLDER,
            t("open_model_folder"),
            "",
            self.modelGroup
        )
        self.openModelFolderCard.hBoxLayout.addWidget(self.openModelFolderBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.openModelFolderCard.hBoxLayout.addSpacing(16)

        # === FOV 與偵測範圍 ===
        self.fovGroup = SettingCardGroup(t("fov_and_detect_range"), self.scrollWidget)

        # FOV 大小 - 使用 SliderSpinCard
        self.fovCard = SliderSpinCard(
            FluentIcon.ZOOM,
            t("fov_size"),
            50, 500,
            description="",
            parent=self.fovGroup
        )

        # FOV 跟隨滑鼠
        self.fovFollowCard = SwitchSettingCard(
            FluentIcon.MOVE,
            t("fov_follow_mouse"),
            "",
            parent=self.fovGroup
        )

        # AI 偵測範圍 - 使用 SliderSpinCard
        self.detectRangeCard = SliderSpinCard(
            FluentIcon.FULL_SCREEN,
            t("detect_range_size"),
            100, 1080,
            description=t("detect_range_note"),
            parent=self.fovGroup
        )

        # === 通用參數 ===
        self.generalGroup = SettingCardGroup(t("general_params"), self.scrollWidget)

        # 偵測間隔 - 使用 SliderSpinCard
        self.detectIntervalCard = SliderSpinCard(
            FluentIcon.SPEED_HIGH,
            t("detect_interval"),
            1, 100,
            suffix="ms",
            description="",
            parent=self.generalGroup
        )

        # 最低信心值 - 使用 SliderSpinCard
        self.confidenceCard = SliderSpinCard(
            FluentIcon.CERTIFICATE,
            t("min_confidence"),
            1, 100,
            suffix="%",
            description="",
            parent=self.generalGroup
        )

        # 瞄準部位
        self.aimPartCombo = ComboBox()
        self.aimPartCombo.addItems([t("head"), t("body"), t("both")])
        self.aimPartCombo.setMinimumWidth(120)
        self.aimPartCard = SettingCard(
            FluentIcon.PEOPLE,
            t("aim_part"),
            "",
            self.generalGroup
        )
        self.aimPartCard.hBoxLayout.addWidget(self.aimPartCombo, 0, Qt.AlignmentFlag.AlignRight)
        self.aimPartCard.hBoxLayout.addSpacing(16)

        # 滑鼠移動方式
        self.mouseMoveCombo = ComboBox()
        self.mouseMoveCombo.addItems(["ddxoft", "mouse_event", "arduino", "xbox"])
        self.mouseMoveCombo.setMinimumWidth(150)
        self.mouseMoveCard = SettingCard(
            FluentIcon.FINGERPRINT,
            t("mouse_move_method"),
            "",
            self.generalGroup
        )
        self.mouseMoveCard.hBoxLayout.addWidget(self.mouseMoveCombo, 0, Qt.AlignmentFlag.AlignRight)
        self.mouseMoveCard.hBoxLayout.addSpacing(16)

        # 持續自動瞄準（不需按瞄準鍵）
        self.alwaysAimCard = SwitchSettingCard(
            FluentIcon.FINGERPRINT,
            t("always_aim"),
            "",
            parent=self.generalGroup
        )

        # 保持偵測（即使未按瞄準鍵）
        self.keepDetectingCard = SwitchSettingCard(
            FluentIcon.UPDATE,
            t("keep_detecting"),
            "",
            parent=self.generalGroup
        )

        # 單一目標模式
        self.singleTargetCard = SwitchSettingCard(
            FluentIcon.PEOPLE,
            t("sticky_target_enabled"),
            "",
            parent=self.generalGroup
        )

        self.aimDeadzoneCard = SliderSpinCard(
            FluentIcon.REMOVE,
            t("aim_position_deadzone_px"),
            0, 20,
            suffix="px",
            description="",
            parent=self.generalGroup
        )

        self.lockRadiusCard = SliderSpinCard(
            FluentIcon.ZOOM,
            t("lock_retain_radius_px"),
            8, 300,
            suffix="px",
            description="",
            parent=self.generalGroup
        )

        self.lockTimeCard = SliderSpinCard(
            FluentIcon.HISTORY,
            t("lock_retain_time_s"),
            0, 500,
            suffix="ms",
            description="",
            parent=self.generalGroup
        )

        # === Arduino 設定（僅在選擇 arduino 時顯示）===
        self.arduinoGroup = SettingCardGroup("Arduino", self.scrollWidget)

        # COM 埠選擇
        self.comPortCombo = ComboBox()
        self.comPortCombo.setMinimumWidth(120)
        self.comPortCombo.addItem(t("no_com_port"))
        self._refreshComPorts()

        self.comRefreshBtn = PushButton(t("refresh"))
        self.comRefreshBtn.setFixedWidth(80)

        self.comPortCard = SettingCard(
            FluentIcon.CONNECT,
            t("arduino_com_port"),
            "",
            self.arduinoGroup
        )
        self.comPortCard.hBoxLayout.addWidget(self.comPortCombo, 0, Qt.AlignmentFlag.AlignRight)
        self.comPortCard.hBoxLayout.addWidget(self.comRefreshBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.comPortCard.hBoxLayout.addSpacing(16)

        # 連線狀態
        self._isArduinoConnected = False
        self.connectionLabel = BodyLabel(t("disconnected"))
        self.connectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self.connectionCard = SettingCard(
            FluentIcon.WIFI,
            t("connected") + " / " + t("disconnected"),
            "",
            self.arduinoGroup
        )
        self.connectionCard.hBoxLayout.addWidget(self.connectionLabel, 0, Qt.AlignmentFlag.AlignRight)
        self.connectionCard.hBoxLayout.addSpacing(16)

        # Arduino 連線/斷線按鈕
        self.arduinoConnectBtn = PushButton(t("arduino_connect"))
        self.arduinoConnectBtn.setFixedWidth(120)
        self.arduinoConnectCard = SettingCard(
            FluentIcon.LINK,
            t("arduino_connect"),
            t("arduino_connect_desc"),
            self.arduinoGroup
        )
        self.arduinoConnectCard.hBoxLayout.addWidget(self.arduinoConnectBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.arduinoConnectCard.hBoxLayout.addSpacing(16)

        # 使用教學
        self.guideBtn = PushButton(t("arduino_guide"))
        self.guideCard = SettingCard(
            FluentIcon.BOOK_SHELF,
            t("arduino_guide"),
            "",
            self.arduinoGroup
        )
        self.guideCard.hBoxLayout.addWidget(self.guideBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.guideCard.hBoxLayout.addSpacing(16)

        # 一鍵硬體偽裝
        self.spoofBtn = PushButton(t("spoof_device"))
        self.spoofCard = SettingCard(
            FluentIcon.VPN,
            t("spoof_device"),
            "",
            self.arduinoGroup
        )
        self.spoofCard.hBoxLayout.addWidget(self.spoofBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.spoofCard.hBoxLayout.addSpacing(16)

        # 驗證偽裝
        self.verifySpoofBtn = PushButton(t("verify_spoof"))
        self.verifySpoofCard = SettingCard(
            FluentIcon.ACCEPT,
            t("verify_spoof"),
            "",
            self.arduinoGroup
        )
        self.verifySpoofCard.hBoxLayout.addWidget(self.verifySpoofBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.verifySpoofCard.hBoxLayout.addSpacing(16)

        # 測試愛心移動
        self.testHeartBtn = PushButton(t("test_move_heart"))
        self.testHeartCard = SettingCard(
            FluentIcon.HEART,
            t("test_move_heart"),
            "",
            self.arduinoGroup
        )
        self.testHeartCard.hBoxLayout.addWidget(self.testHeartBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.testHeartCard.hBoxLayout.addSpacing(16)

        # === Xbox 360 虛擬手把設定（僅在選擇 xbox 時顯示）===
        self.xboxGroup = SettingCardGroup("Xbox 360 Controller", self.scrollWidget)

        # 靈敏度
        self.xboxSensitivityCard = SliderSpinCard(
            FluentIcon.SPEED_HIGH,
            t("xbox_sensitivity"),
            10, 500,
            suffix="%",
            description="",
            parent=self.xboxGroup
        )

        # 死區
        self.xboxDeadzoneCard = SliderSpinCard(
            FluentIcon.REMOVE,
            t("xbox_deadzone"),
            0, 50,
            suffix="%",
            description="",
            parent=self.xboxGroup
        )

        # 連線狀態
        self._isXboxConnected = False
        self.xboxConnectionLabel = BodyLabel(t("disconnected"))
        self.xboxConnectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")
        self.xboxConnectionCard = SettingCard(
            FluentIcon.GAME,
            t("connected") + " / " + t("disconnected"),
            "",
            self.xboxGroup
        )
        self.xboxConnectionCard.hBoxLayout.addWidget(self.xboxConnectionLabel, 0, Qt.AlignmentFlag.AlignRight)
        self.xboxConnectionCard.hBoxLayout.addSpacing(16)

        # 手動連線/斷線按鈕
        self.xboxConnectBtn = PushButton(t("xbox_connect"))
        self.xboxConnectBtn.setFixedWidth(120)
        self.xboxConnectCard = SettingCard(
            FluentIcon.WIFI,
            t("xbox_connect"),
            t("xbox_connect_desc"),
            self.xboxGroup
        )
        self.xboxConnectCard.hBoxLayout.addWidget(self.xboxConnectBtn, 0, Qt.AlignmentFlag.AlignRight)
        self.xboxConnectCard.hBoxLayout.addSpacing(16)

        # === PID 參數 ===
        self.pidGroup = SettingCardGroup(t("aim_speed_pid"), self.scrollWidget)

        # X/Y 軸切換器
        self.pidAxisPivot = SegmentedWidget()
        self.pidAxisPivot.addItem(routeKey='x', text=t("horizontal_x"))
        self.pidAxisPivot.addItem(routeKey='y', text=t("vertical_y"))
        self.pidAxisPivot.setCurrentItem('x')
        self.pidAxisPivot.currentItemChanged.connect(self._onPidAxisChanged)

        # 堆疊容器
        self.pidStackedWidget = QStackedWidget()

        # P - 反應速度 X - 使用 SliderLabelCard
        self.pidPxCard = SliderLabelCard(
            FluentIcon.SPEED_HIGH,
            t("reaction_speed_p"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # I - 誤差修正 X - 使用 SliderLabelCard
        self.pidIxCard = SliderLabelCard(
            FluentIcon.SYNC,
            t("error_correction_i"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # D - 穩定控制 X - 使用 SliderLabelCard
        self.pidDxCard = SliderLabelCard(
            FluentIcon.ALIGNMENT,
            t("stability_suppression_d"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # P - 反應速度 Y - 使用 SliderLabelCard
        self.pidPyCard = SliderLabelCard(
            FluentIcon.SPEED_HIGH,
            t("reaction_speed_p"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # I - 誤差修正 Y - 使用 SliderLabelCard
        self.pidIyCard = SliderLabelCard(
            FluentIcon.SYNC,
            t("error_correction_i"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # D - 穩定控制 Y - 使用 SliderLabelCard
        self.pidDyCard = SliderLabelCard(
            FluentIcon.ALIGNMENT,
            t("stability_suppression_d"),
            0, 100,
            format_func=lambda v: f"{v/100:.2f}",
            parent=self.pidGroup
        )

        # === 貝塞爾曲線 ===
        self.bezierGroup = SettingCardGroup(t("bezier_curve"), self.scrollWidget)

        # 啟用開關
        self.bezierEnableCard = SwitchSettingCard(
            FluentIcon.CALORIES,
            t("bezier_curve_enable"),
            "",
            parent=self.bezierGroup
        )

        # 曲線彎曲程度 - 使用 SliderLabelCard
        self.bezierStrengthCard = SliderLabelCard(
            FluentIcon.MIX_VOLUMES,
            t("bezier_curve_strength"),
            0, 100,
            format_func=lambda v: f"{v}%",
            parent=self.bezierGroup
        )

        # 曲線分段數 - 使用 SliderLabelCard
        self.bezierStepsCard = SliderLabelCard(
            FluentIcon.MORE,
            t("bezier_curve_steps"),
            2, 20,
            format_func=lambda v: str(v),
            parent=self.bezierGroup
        )

        # === 智慧追蹤 ===
        self.trackerGroup = SettingCardGroup(t("tracker_prediction"), self.scrollWidget)

        # 啟用開關
        self.trackerEnableCard = SwitchSettingCard(
            FluentIcon.RINGER,
            t("tracker_enable"),
            "",
            parent=self.trackerGroup
        )

        # 預判時間 - 使用 SliderLabelCard
        self.trackerTimeCard = SliderLabelCard(
            FluentIcon.HISTORY,
            t("tracker_prediction_time"),
            0, 100,
            format_func=lambda v: f"{v} ms",
            label_width=50,
            parent=self.trackerGroup
        )

        # 速度平滑係數 - 使用 SliderLabelCard
        self.trackerSmoothCard = SliderLabelCard(
            FluentIcon.SPEED_MEDIUM,
            t("tracker_smoothing_factor"),
            0, 100,
            format_func=lambda v: f"{v}%",
            parent=self.trackerGroup
        )

        # 靜止判定速度 - 使用 SliderLabelCard
        self.trackerThresholdCard = SliderLabelCard(
            FluentIcon.STOP_WATCH,
            t("tracker_stop_threshold"),
            0, 100,
            format_func=lambda v: f"{v} px/s",
            label_width=55,
            parent=self.trackerGroup
        )

        # 顯示預判視覺化
        self.predictionMaxDistanceCard = SliderLabelCard(
            FluentIcon.MOVE,
            t("prediction_max_distance_px"),
            0, 100,
            format_func=lambda v: f"{v} px",
            label_width=55,
            parent=self.trackerGroup
        )

        self.trackerShowCard = SwitchSettingCard(
            FluentIcon.VIEW,
            t("tracker_show_prediction"),
            "",
            parent=self.trackerGroup
        )

    def _initLayout(self):
        """排版所有控制項"""
        # 模型設定
        self.modelGroup.addSettingCard(self.modelCard)
        self.modelGroup.addSettingCard(self.activeClassCard)
        self.modelGroup.addSettingCard(self.openModelFolderCard)
        self.addContent(self.modelGroup)

        # FOV 與偵測範圍
        self.fovGroup.addSettingCard(self.fovCard)
        self.fovGroup.addSettingCard(self.fovFollowCard)
        self.fovGroup.addSettingCard(self.detectRangeCard)
        self.addContent(self.fovGroup)

        # 通用參數
        self.generalGroup.addSettingCard(self.detectIntervalCard)
        self.generalGroup.addSettingCard(self.confidenceCard)
        self.generalGroup.addSettingCard(self.aimPartCard)
        self.generalGroup.addSettingCard(self.mouseMoveCard)
        self.generalGroup.addSettingCard(self.alwaysAimCard)
        self.generalGroup.addSettingCard(self.keepDetectingCard)
        self.generalGroup.addSettingCard(self.singleTargetCard)
        self.generalGroup.addSettingCard(self.aimDeadzoneCard)
        self.generalGroup.addSettingCard(self.lockRadiusCard)
        self.generalGroup.addSettingCard(self.lockTimeCard)
        self.addContent(self.generalGroup)

        # Arduino 設定（在滑鼠移動方式下方）
        self.arduinoGroup.addSettingCard(self.comPortCard)
        self.arduinoGroup.addSettingCard(self.connectionCard)
        self.arduinoGroup.addSettingCard(self.arduinoConnectCard)
        self.arduinoGroup.addSettingCard(self.guideCard)
        self.arduinoGroup.addSettingCard(self.spoofCard)
        self.arduinoGroup.addSettingCard(self.verifySpoofCard)
        self.arduinoGroup.addSettingCard(self.testHeartCard)
        self.addContent(self.arduinoGroup)
        # 預設隱藏 Arduino 設定
        self.arduinoGroup.setVisible(False)

        # Xbox 360 設定（在 Arduino 設定下方）
        self.xboxGroup.addSettingCard(self.xboxSensitivityCard)
        self.xboxGroup.addSettingCard(self.xboxDeadzoneCard)
        self.xboxGroup.addSettingCard(self.xboxConnectionCard)
        self.xboxGroup.addSettingCard(self.xboxConnectCard)
        self.addContent(self.xboxGroup)
        # 預設隱藏 Xbox 設定
        self.xboxGroup.setVisible(False)

        # === 進階設定（摺疊區域）===

        # PID 參數 - 使用切換式佈局
        # 切換器容器
        pivotWidget = QWidget()
        pivotLayout = QHBoxLayout(pivotWidget)
        pivotLayout.setContentsMargins(16, 8, 16, 8)
        pivotLayout.addWidget(self.pidAxisPivot)
        pivotLayout.addStretch(1)

        # X 軸頁面
        self.pidXPage = QWidget()
        xPageLayout = QVBoxLayout(self.pidXPage)
        xPageLayout.setContentsMargins(0, 0, 0, 0)
        xPageLayout.setSpacing(0)
        xPageLayout.addWidget(self.pidPxCard)
        xPageLayout.addWidget(self.pidIxCard)
        xPageLayout.addWidget(self.pidDxCard)

        # Y 軸頁面
        self.pidYPage = QWidget()
        yPageLayout = QVBoxLayout(self.pidYPage)
        yPageLayout.setContentsMargins(0, 0, 0, 0)
        yPageLayout.setSpacing(0)
        yPageLayout.addWidget(self.pidPyCard)
        yPageLayout.addWidget(self.pidIyCard)
        yPageLayout.addWidget(self.pidDyCard)

        # 加入堆疊
        self.pidStackedWidget.addWidget(self.pidXPage)
        self.pidStackedWidget.addWidget(self.pidYPage)

        # 組合到 pidGroup
        self.pidGroup.vBoxLayout.addWidget(pivotWidget)
        self.pidGroup.vBoxLayout.addWidget(self.pidStackedWidget)

        # 貝塞爾曲線
        self.bezierGroup.addSettingCard(self.bezierEnableCard)
        self.bezierGroup.addSettingCard(self.bezierStrengthCard)
        self.bezierGroup.addSettingCard(self.bezierStepsCard)

        # 智慧追蹤
        self.trackerGroup.addSettingCard(self.trackerEnableCard)
        self.trackerGroup.addSettingCard(self.trackerTimeCard)
        self.trackerGroup.addSettingCard(self.trackerSmoothCard)
        self.trackerGroup.addSettingCard(self.trackerThresholdCard)
        self.trackerGroup.addSettingCard(self.predictionMaxDistanceCard)
        self.trackerGroup.addSettingCard(self.trackerShowCard)

        # 將進階設定添加到摺疊區域
        self.addContent(self.pidGroup)
        self.addContent(self.bezierGroup)
        self.addContent(self.trackerGroup)

        self.scrollLayout.addStretch(1)

    def _connectSignals(self):
        """連接信號"""
        # 模型
        self.modelCombo.currentTextChanged.connect(self._onModelChanged)
        self.activeClassCombo.currentTextChanged.connect(self._onActiveClassChanged)
        self.openModelFolderBtn.clicked.connect(self._openModelFolder)

        # FOV 與偵測範圍 - 使用新組件的 valueChanged 信號
        self.fovCard.valueChanged.connect(self._onFovChanged)
        self.fovFollowCard.checkedChanged.connect(self._onFovFollowChanged)
        self.detectRangeCard.valueChanged.connect(self._onDetectRangeChanged)

        # 通用參數 - 使用新組件的 valueChanged 信號
        self.detectIntervalCard.valueChanged.connect(self._onDetectIntervalChanged)
        self.confidenceCard.valueChanged.connect(self._onConfidenceChanged)
        self.aimPartCombo.currentIndexChanged.connect(self._onAimPartChanged)
        self.mouseMoveCombo.currentTextChanged.connect(self._onMouseMoveChanged)
        self.alwaysAimCard.checkedChanged.connect(self._onAlwaysAimChanged)
        self.keepDetectingCard.checkedChanged.connect(self._onKeepDetectingChanged)
        self.singleTargetCard.checkedChanged.connect(self._onSingleTargetChanged)
        self.aimDeadzoneCard.valueChanged.connect(self._onAimDeadzoneChanged)
        self.lockRadiusCard.valueChanged.connect(self._onLockRadiusChanged)
        self.lockTimeCard.valueChanged.connect(self._onLockTimeChanged)

        # Arduino 相關信號
        self.comRefreshBtn.clicked.connect(self._refreshComPorts)
        self.comPortCombo.currentTextChanged.connect(self._onComPortChanged)
        self.arduinoConnectBtn.clicked.connect(self._onArduinoConnectToggle)
        self.guideBtn.clicked.connect(self._onOpenGuide)
        self.spoofBtn.clicked.connect(self._onSpoofDevice)
        self.verifySpoofBtn.clicked.connect(self._onVerifySpoof)
        self.testHeartBtn.clicked.connect(self._onTestHeart)

        # Xbox 相關信號
        self.xboxSensitivityCard.valueChanged.connect(self._onXboxSensitivityChanged)
        self.xboxDeadzoneCard.valueChanged.connect(self._onXboxDeadzoneChanged)
        self.xboxConnectBtn.clicked.connect(self._onXboxConnectToggle)

        # PID - 使用新組件的 valueChanged 信號
        self.pidPxCard.valueChanged.connect(lambda v: self._onPidChanged('pid_kp_x', v))
        self.pidIxCard.valueChanged.connect(lambda v: self._onPidChanged('pid_ki_x', v))
        self.pidDxCard.valueChanged.connect(lambda v: self._onPidChanged('pid_kd_x', v))
        self.pidPyCard.valueChanged.connect(lambda v: self._onPidChanged('pid_kp_y', v))
        self.pidIyCard.valueChanged.connect(lambda v: self._onPidChanged('pid_ki_y', v))
        self.pidDyCard.valueChanged.connect(lambda v: self._onPidChanged('pid_kd_y', v))

        # 貝塞爾 - 使用新組件的 valueChanged 信號
        self.bezierEnableCard.checkedChanged.connect(self._onBezierEnableChanged)
        self.bezierStrengthCard.valueChanged.connect(self._onBezierStrengthChanged)
        self.bezierStepsCard.valueChanged.connect(self._onBezierStepsChanged)

        # 追蹤 - 使用新組件的 valueChanged 信號
        self.trackerEnableCard.checkedChanged.connect(self._onTrackerEnableChanged)
        self.trackerTimeCard.valueChanged.connect(self._onTrackerTimeChanged)
        self.trackerSmoothCard.valueChanged.connect(self._onTrackerSmoothChanged)
        self.trackerThresholdCard.valueChanged.connect(self._onTrackerThresholdChanged)
        self.predictionMaxDistanceCard.valueChanged.connect(self._onPredictionMaxDistanceChanged)
        self.trackerShowCard.checkedChanged.connect(self._onTrackerShowChanged)

    def _loadFromConfig(self):
        """從 Config 載入值"""
        if not self._config:
            return

        self._updateModelConstraintControls()

        # 刷新模型列表並選中當前模型（暫時阻斷信號避免覆蓋設定）
        self.modelCombo.blockSignals(True)
        self._refreshModelList()
        model_spec = get_model_spec(getattr(self._config, 'model_id', ''))
        model_name = model_spec.display_name if model_spec else os.path.basename(self._config.model_path)

        # 大小寫不敏感比對
        idx = -1
        for i in range(self.modelCombo.count()):
            if self.modelCombo.itemText(i).lower() == model_name.lower():
                idx = i
                break

        if idx >= 0:
            self.modelCombo.setCurrentIndex(idx)
        self.modelCombo.blockSignals(False)
        self._refreshTargetClassList()

        # FOV 與偵測範圍 - 使用新組件的 setValue
        self.fovCard.setValue(self._config.fov_size)
        self.fovFollowCard.setChecked(self._config.fov_follow_mouse)
        self.detectRangeCard.setValue(self._config.detect_range_size)

        # 通用參數 - 使用新組件的 setValue
        interval_ms = int(self._config.detect_interval * 1000)
        self.detectIntervalCard.setValue(interval_ms)
        confidence_pct = int(self._config.min_confidence * 100)
        self.confidenceCard.setValue(confidence_pct)

        aim_parts = ["head", "body", "both"]
        if self._config.aim_part in aim_parts:
            self.aimPartCombo.setCurrentIndex(aim_parts.index(self._config.aim_part))
        self.aimPartCard.setVisible(False)

        mouse_methods = ["ddxoft", "mouse_event", "arduino", "xbox"]
        if self._config.mouse_move_method in mouse_methods:
            self.mouseMoveCombo.setCurrentIndex(mouse_methods.index(self._config.mouse_move_method))
        self.alwaysAimCard.setChecked(getattr(self._config, 'always_aim', False))
        self.keepDetectingCard.setChecked(getattr(self._config, 'keep_detecting', False))
        self.singleTargetCard.setChecked(getattr(self._config, 'sticky_target_enabled', True))
        self.aimDeadzoneCard.setValue(int(getattr(self._config, 'aim_position_deadzone_px', 3.0)))
        self.lockRadiusCard.setValue(int(getattr(self._config, 'lock_retain_radius_px', 48.0)))
        self.lockTimeCard.setValue(int(getattr(self._config, 'lock_retain_time_s', 0.12) * 1000))

        # 根據當前選擇的移動方式顯示/隱藏 Arduino 和 Xbox 設定
        self._updateMethodGroupVisibility(self._config.mouse_move_method)

        # COM 埠
        if self._config.arduino_com_port:
            idx = self.comPortCombo.findText(self._config.arduino_com_port)
            if idx >= 0:
                self.comPortCombo.setCurrentIndex(idx)

        # PID - 使用新組件的 setValue
        self.pidPxCard.setValue(int(self._config.pid_kp_x * 100))
        self.pidIxCard.setValue(int(self._config.pid_ki_x * 100))
        self.pidDxCard.setValue(int(self._config.pid_kd_x * 100))
        self.pidPyCard.setValue(int(self._config.pid_kp_y * 100))
        self.pidIyCard.setValue(int(self._config.pid_ki_y * 100))
        self.pidDyCard.setValue(int(self._config.pid_kd_y * 100))

        # 貝塞爾 - 使用新組件的 setValue
        self.bezierEnableCard.setChecked(self._config.bezier_curve_enabled)
        self.bezierStrengthCard.setValue(int(self._config.bezier_curve_strength * 100))
        self.bezierStepsCard.setValue(self._config.bezier_curve_steps)

        # 追蹤 - 使用新組件的 setValue
        self.trackerEnableCard.setChecked(self._config.tracker_enabled)
        self.trackerTimeCard.setValue(int(self._config.prediction_lead_time_s * 1000))
        self.trackerSmoothCard.setValue(int(self._config.velocity_ema_alpha * 100))
        self.trackerThresholdCard.setValue(int(self._config.velocity_deadzone_px_per_s))
        self.predictionMaxDistanceCard.setValue(int(getattr(self._config, 'prediction_max_distance_px', 32.0)))
        self.trackerShowCard.setChecked(self._config.tracker_show_prediction)

        # Xbox 設定
        self.xboxSensitivityCard.setValue(int(getattr(self._config, 'xbox_sensitivity', 1.0) * 100))
        self.xboxDeadzoneCard.setValue(int(getattr(self._config, 'xbox_deadzone', 0.05) * 100))
        self._updateXboxConnectionStatus()

    def _refreshModelList(self):
        """刷新模型列表"""
        self.modelCombo.clear()
        # aim_page.py 位於 src/gui/fluent_app/pages/，向上 4 層到項目根目錄
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        project_root = os.path.dirname(src_dir)
        model_dir = os.path.join(project_root, "Model")
        if os.path.exists(model_dir):
            models = glob.glob(os.path.join(model_dir, "*.engine"))
            for m in models:
                self.modelCombo.addItem(os.path.basename(m))

    def _openModelFolder(self):
        """開啟模型資料夾"""
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        project_root = os.path.dirname(src_dir)
        model_dir = os.path.join(project_root, "Model")
        if os.path.exists(model_dir):
            os.startfile(model_dir)

    def _refreshComPorts(self):
        """刷新 COM 埠列表"""
        self.comPortCombo.clear()
        self.comPortCombo.addItem(t("no_com_port"))

        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            for port in ports:
                self.comPortCombo.addItem(port.device)
        except ImportError:
            pass

    def _updateArduinoVisibility(self, method):
        """根據滑鼠移動方式更新 Arduino 設定的可見性"""
        is_arduino = (method == "arduino")
        self.arduinoGroup.setVisible(is_arduino)

    def _updateMethodGroupVisibility(self, method):
        """根據滑鼠移動方式更新各裝置設定組的可見性"""
        self.arduinoGroup.setVisible(method == "arduino")
        self.xboxGroup.setVisible(method == "xbox")

    # === 回調函數 ===
    def _onModelChanged(self, text):
        if self._config and text:
            self._config.model_path = os.path.join("Model", text)

    def _refreshModelList(self):
        self.modelCombo.clear()
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        project_root = os.path.dirname(src_dir)
        self._model_specs = []
        for spec in list_model_specs():
            model_path = spec.engine_path
            if not os.path.isabs(model_path):
                model_path = os.path.join(project_root, model_path)
            if os.path.exists(model_path):
                self._model_specs.append(spec)
        for spec in self._model_specs:
            self.modelCombo.addItem(spec.display_name)

    def _refreshTargetClassList(self):
        self.activeClassCombo.blockSignals(True)
        self.activeClassCombo.clear()
        if self._config:
            spec = get_model_spec(getattr(self._config, 'model_id', ''))
            if spec:
                for label in spec.labels:
                    self.activeClassCombo.addItem(label.upper())
                if self._config.active_target_class in spec.labels:
                    self.activeClassCombo.setCurrentIndex(spec.labels.index(self._config.active_target_class))
        self.activeClassCombo.blockSignals(False)

    def _onModelChanged(self, text):
        if self._config and text:
            spec = next((item for item in getattr(self, '_model_specs', []) if item.display_name == text), None)
            if spec is None:
                return
            self._config.model_id = spec.model_id
            self._config.model_path = spec.engine_path
            self._config.model_input_size = spec.input_size
            apply_model_constraints(self._config)
            self._updateModelConstraintControls()
            self.fovCard.setValue(self._config.fov_size)
            self.detectRangeCard.setValue(self._config.detect_range_size)
            if self._config.active_target_class not in spec.labels:
                self._config.active_target_class = spec.labels[0]
            self._refreshTargetClassList()

    def _onActiveClassChanged(self, text):
        if self._config and text:
            self._config.active_target_class = text.lower()

    def _onFovChanged(self, value):
        """FOV 改變"""
        if self._config:
            self._config.fov_size = value
            apply_model_constraints(self._config)
            if self.fovCard.value() != self._config.fov_size:
                self.fovCard.setValue(self._config.fov_size)

    def _onFovFollowChanged(self, checked):
        if self._config:
            self._config.fov_follow_mouse = checked

    def _onDetectRangeChanged(self, value):
        """偵測範圍改變"""
        if self._config:
            self._config.detect_range_size = value
            apply_model_constraints(self._config)
            if self.detectRangeCard.value() != self._config.detect_range_size:
                self.detectRangeCard.setValue(self._config.detect_range_size)

    def _onDetectIntervalChanged(self, value):
        """偵測間隔改變"""
        if self._config:
            self._config.detect_interval = value / 1000.0

    def _onConfidenceChanged(self, value):
        """信心值改變"""
        if self._config:
            self._config.min_confidence = value / 100.0

    def _onAimPartChanged(self, index):
        if self._config:
            parts = ["head", "body", "both"]
            self._config.aim_part = parts[index]

    def _onMouseMoveChanged(self, text):
        if self._config:
            self._config.mouse_move_method = text
        # 更新設定組的可見性
        self._updateMethodGroupVisibility(text)

    def _onAlwaysAimChanged(self, checked):
        if self._config:
            self._config.always_aim = checked

    def _onKeepDetectingChanged(self, checked):
        if self._config:
            self._config.keep_detecting = checked

    def _onSingleTargetChanged(self, checked):
        if self._config:
            self._config.sticky_target_enabled = checked

    def _onAimDeadzoneChanged(self, value):
        if self._config:
            self._config.aim_position_deadzone_px = float(value)

    def _onLockRadiusChanged(self, value):
        if self._config:
            self._config.lock_retain_radius_px = float(value)

    def _onLockTimeChanged(self, value):
        if self._config:
            self._config.lock_retain_time_s = value / 1000.0

    def _onComPortChanged(self, text):
        if self._config and text != t("no_com_port"):
            self._config.arduino_com_port = text

    def _onOpenGuide(self):
        """開啟 Arduino 使用教學"""
        guide_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
            "Arduino_User_Guide.html"
        )
        if os.path.exists(guide_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(guide_path))

    def _onSpoofDevice(self):
        """一鍵硬體偽裝"""
        reply = QMessageBox.question(
            self, t("spoof_confirm_title"),
            t("spoof_confirm_msg").replace("\\n", "\n"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                from win_utils.arduino_spoofer import spoof_arduino_board
                success, boards_path = spoof_arduino_board()
                if success:
                    QMessageBox.information(
                        self, t("spoof_success_title"),
                        t("spoof_success_msg").replace("\\n", "\n")
                    )
                else:
                    QMessageBox.warning(
                        self, t("spoof_error_title"),
                        f"Spoof operation returned unsuccessful.\nFile: {boards_path}"
                    )
            except FileNotFoundError as e:
                QMessageBox.warning(self, t("spoof_error_title"), str(e))
            except PermissionError as e:
                QMessageBox.warning(self, t("spoof_error_title"), str(e))
            except Exception as e:
                QMessageBox.critical(self, t("spoof_error_title"), f"Error: {e}")

    def _onVerifySpoof(self):
        """驗證偽裝"""
        try:
            from win_utils.arduino_spoofer import verify_spoof
            specific_port = None
            if self._config and self._config.arduino_com_port:
                specific_port = self._config.arduino_com_port
            is_spoofed, message = verify_spoof(specific_port)
            if is_spoofed:
                QMessageBox.information(
                    self, t("verify_success_title"), message
                )
            else:
                QMessageBox.warning(
                    self, t("verify_fail_title"), message
                )
        except Exception as e:
            QMessageBox.critical(
                self, t("verify_fail_title"), f"Error: {e}"
            )

    def _onTestHeart(self):
        """測試愛心移動"""
        reply = QMessageBox.question(
            self, t("test_heart_confirm_title"),
            t("test_heart_confirm_msg").replace("\\n", "\n"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            import time
            from win_utils.arduino_mouse import arduino_mouse

            if not arduino_mouse.is_connected():
                # 嘗試使用設定中的 COM port 連線
                com_port = self._config.arduino_com_port if self._config else ""
                if not com_port:
                    QMessageBox.warning(
                        self, t("test_heart_confirm_title"),
                        "Arduino not connected. Please set COM port first."
                    )
                    return
                if not arduino_mouse.connect(com_port):
                    QMessageBox.warning(
                        self, t("test_heart_confirm_title"),
                        f"Failed to connect to {com_port}."
                    )
                    return

            def _draw_heart():
                """在背景執行緒中繪製愛心圖案"""
                # 心形參數方程式: x = 16sin³(t), y = 13cos(t) - 5cos(2t) - 2cos(3t) - cos(4t)
                num_steps = 120
                scale = 3.0
                points = []
                for i in range(num_steps + 1):
                    angle = 2 * math.pi * i / num_steps
                    x = 16 * (math.sin(angle) ** 3)
                    y = -(13 * math.cos(angle) - 5 * math.cos(2 * angle)
                           - 2 * math.cos(3 * angle) - math.cos(4 * angle))
                    points.append((x * scale, y * scale))

                # 計算相鄰點之間的增量並發送
                for i in range(1, len(points)):
                    dx = int(round(points[i][0] - points[i - 1][0]))
                    dy = int(round(points[i][1] - points[i - 1][1]))
                    if dx != 0 or dy != 0:
                        arduino_mouse.move(dx, dy)
                    time.sleep(0.015)

            # 在背景執行緒中執行，避免阻塞 GUI
            thread = threading.Thread(target=_draw_heart, daemon=True)
            thread.start()

    def _onPidAxisChanged(self, routeKey: str):
        """切換 PID X/Y 軸頁面"""
        if routeKey == 'x':
            self.pidStackedWidget.setCurrentIndex(0)
        else:
            self.pidStackedWidget.setCurrentIndex(1)

    def _onPidChanged(self, attr, value):
        if self._config:
            float_val = value / 100.0
            setattr(self._config, attr, float_val)

    def _onBezierEnableChanged(self, checked):
        if self._config:
            self._config.bezier_curve_enabled = checked

    def _onBezierStrengthChanged(self, value):
        if self._config:
            self._config.bezier_curve_strength = value / 100.0

    def _onBezierStepsChanged(self, value):
        if self._config:
            self._config.bezier_curve_steps = value

    def _onTrackerEnableChanged(self, checked):
        if self._config:
            self._config.tracker_enabled = checked

    def _onTrackerTimeChanged(self, value):
        if self._config:
            self._config.prediction_lead_time_s = value / 1000.0

    def _onTrackerSmoothChanged(self, value):
        if self._config:
            self._config.velocity_ema_alpha = value / 100.0

    def _onTrackerThresholdChanged(self, value):
        if self._config:
            self._config.velocity_deadzone_px_per_s = float(value)

    def _onPredictionMaxDistanceChanged(self, value):
        if self._config:
            self._config.prediction_max_distance_px = float(value)

    def _onTrackerShowChanged(self, checked):
        if self._config:
            self._config.tracker_show_prediction = checked

    # === Arduino 連線回調函數 ===
    def _onArduinoConnectToggle(self):
        """Arduino 連線/斷線切換"""
        try:
            from win_utils import is_arduino_connected, connect_arduino, disconnect_arduino
            if is_arduino_connected():
                disconnect_arduino()
            else:
                com_port = self.comPortCombo.currentText()
                if not com_port or com_port == t("no_com_port"):
                    QMessageBox.warning(
                        self, t("config_error"),
                        t("no_com_port")
                    )
                    return
                success = connect_arduino(com_port)
                if not success:
                    QMessageBox.warning(
                        self, t("config_error"),
                        f"Arduino {t('disconnected')}: {com_port}"
                    )
            self._updateArduinoConnectionStatus()
        except ImportError:
            QMessageBox.warning(
                self, t("config_error"),
                "pyserial not installed.\npip install pyserial"
            )

    def _updateArduinoConnectionStatus(self):
        """更新 Arduino 連線狀態顯示"""
        try:
            from win_utils import is_arduino_connected
            if is_arduino_connected():
                self._isArduinoConnected = True
                self.connectionLabel.setText(t("connected"))
                self.connectionLabel.setStyleSheet("color: #2ecc71; font-weight: bold;")
                self.arduinoConnectBtn.setText(t("arduino_disconnect"))
            else:
                self._isArduinoConnected = False
                self.connectionLabel.setText(t("disconnected"))
                self.connectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.arduinoConnectBtn.setText(t("arduino_connect"))
        except ImportError:
            self.connectionLabel.setText("pyserial N/A")
            self.connectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")

    # === Xbox 360 回調函數 ===
    def _onXboxSensitivityChanged(self, value):
        """Xbox 靈敏度改變"""
        if self._config:
            self._config.xbox_sensitivity = value / 100.0
            try:
                from win_utils import set_xbox_sensitivity
                set_xbox_sensitivity(value / 100.0)
            except ImportError:
                pass

    def _onXboxDeadzoneChanged(self, value):
        """Xbox 死區改變"""
        if self._config:
            self._config.xbox_deadzone = value / 100.0
            try:
                from win_utils import set_xbox_deadzone
                set_xbox_deadzone(value / 100.0)
            except ImportError:
                pass

    def _onXboxConnectToggle(self):
        """Xbox 手把連線/斷線切換"""
        try:
            from win_utils import is_xbox_connected, connect_xbox, disconnect_xbox
            if is_xbox_connected():
                disconnect_xbox()
            else:
                connect_xbox()
            self._updateXboxConnectionStatus()
        except ImportError:
            QMessageBox.warning(
                self, t("config_error"),
                "vgamepad 未安裝。\n請執行: pip install vgamepad\n並安裝 ViGEmBus 驅動。"
            )

    def _updateXboxConnectionStatus(self):
        """更新 Xbox 連線狀態顯示"""
        try:
            from win_utils import is_xbox_connected, is_xbox_available
            if not is_xbox_available():
                self.xboxConnectionLabel.setText("vgamepad " + t("disconnected"))
                self.xboxConnectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.xboxConnectBtn.setText(t("xbox_connect"))
                return
                
            if is_xbox_connected():
                self._isXboxConnected = True
                self.xboxConnectionLabel.setText(t("connected"))
                self.xboxConnectionLabel.setStyleSheet("color: #2ecc71; font-weight: bold;")
                self.xboxConnectBtn.setText(t("xbox_disconnect"))
            else:
                self._isXboxConnected = False
                self.xboxConnectionLabel.setText(t("disconnected"))
                self.xboxConnectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")
                self.xboxConnectBtn.setText(t("xbox_connect"))
        except ImportError:
            self.xboxConnectionLabel.setText("vgamepad N/A")
            self.xboxConnectionLabel.setStyleSheet("color: #e74c3c; font-weight: bold;")

    def retranslateUi(self):
        """刷新翻譯"""
        super().retranslateUi()

        # 群組標題
        self.modelGroup.titleLabel.setText(t("model_settings"))
        self.fovGroup.titleLabel.setText(t("fov_and_detect_range"))
        self.generalGroup.titleLabel.setText(t("general_params"))
        self.pidGroup.titleLabel.setText(t("aim_speed_pid"))
        self.bezierGroup.titleLabel.setText(t("bezier_curve"))
        self.trackerGroup.titleLabel.setText(t("tracker_prediction"))

        # 模型設定
        self.modelCard.titleLabel.setText(t("model"))
        self.activeClassCard.titleLabel.setText(t("active_target_class"))
        self.openModelFolderCard.titleLabel.setText(t("open_model_folder"))
        self.openModelFolderBtn.setText(t("open_model_folder"))

        # FOV 與偵測範圍
        self.fovCard.titleLabel.setText(t("fov_size"))
        self.fovFollowCard.titleLabel.setText(t("fov_follow_mouse"))
        self.detectRangeCard.titleLabel.setText(t("detect_range_size"))
        self.detectRangeCard.contentLabel.setText(t("detect_range_note"))

        # 通用參數
        self.detectIntervalCard.titleLabel.setText(t("detect_interval"))
        self.confidenceCard.titleLabel.setText(t("min_confidence"))
        self.aimPartCard.titleLabel.setText(t("aim_part"))
        self.mouseMoveCard.titleLabel.setText(t("mouse_move_method"))
        self.alwaysAimCard.titleLabel.setText(t("always_aim"))
        self.keepDetectingCard.titleLabel.setText(t("keep_detecting"))
        self.singleTargetCard.titleLabel.setText(t("sticky_target_enabled"))
        self.aimDeadzoneCard.titleLabel.setText(t("aim_position_deadzone_px"))
        self.lockRadiusCard.titleLabel.setText(t("lock_retain_radius_px"))
        self.lockTimeCard.titleLabel.setText(t("lock_retain_time_s"))

        # Arduino 設定
        self.comPortCard.titleLabel.setText(t("arduino_com_port"))
        self.comRefreshBtn.setText(t("refresh"))
        self.connectionCard.titleLabel.setText(t("connected") + " / " + t("disconnected"))
        self.arduinoConnectCard.titleLabel.setText(t("arduino_connect"))
        self.arduinoConnectCard.contentLabel.setText(t("arduino_connect_desc"))
        self._updateArduinoConnectionStatus()
        self.guideCard.titleLabel.setText(t("arduino_guide"))
        self.guideBtn.setText(t("arduino_guide"))
        self.spoofCard.titleLabel.setText(t("spoof_device"))
        self.spoofBtn.setText(t("spoof_device"))
        self.verifySpoofCard.titleLabel.setText(t("verify_spoof"))
        self.verifySpoofBtn.setText(t("verify_spoof"))
        self.testHeartCard.titleLabel.setText(t("test_move_heart"))
        self.testHeartBtn.setText(t("test_move_heart"))

        # Xbox 設定
        self.xboxSensitivityCard.titleLabel.setText(t("xbox_sensitivity"))
        self.xboxDeadzoneCard.titleLabel.setText(t("xbox_deadzone"))
        self.xboxConnectionCard.titleLabel.setText(t("connected") + " / " + t("disconnected"))
        self.xboxConnectCard.titleLabel.setText(t("xbox_connect"))
        self.xboxConnectCard.contentLabel.setText(t("xbox_connect_desc"))

        # 更新 ComboBox 內容
        current_aim = self.aimPartCombo.currentIndex()
        self.aimPartCombo.clear()
        self.aimPartCombo.addItems([t("head"), t("body"), t("both")])
        self.aimPartCombo.setCurrentIndex(current_aim)

        # PID
        self.pidAxisPivot.setItemText('x', t("horizontal_x"))
        self.pidAxisPivot.setItemText('y', t("vertical_y"))
        self.pidPxCard.titleLabel.setText(t("reaction_speed_p"))
        self.pidIxCard.titleLabel.setText(t("error_correction_i"))
        self.pidDxCard.titleLabel.setText(t("stability_suppression_d"))
        self.pidPyCard.titleLabel.setText(t("reaction_speed_p"))
        self.pidIyCard.titleLabel.setText(t("error_correction_i"))
        self.pidDyCard.titleLabel.setText(t("stability_suppression_d"))

        # 貝塞爾
        self.bezierEnableCard.titleLabel.setText(t("bezier_curve_enable"))
        self.bezierStrengthCard.titleLabel.setText(t("bezier_curve_strength"))
        self.bezierStepsCard.titleLabel.setText(t("bezier_curve_steps"))

        # 追蹤
        self.trackerEnableCard.titleLabel.setText(t("tracker_enable"))
        self.trackerTimeCard.titleLabel.setText(t("tracker_prediction_time"))
        self.trackerSmoothCard.titleLabel.setText(t("tracker_smoothing_factor"))
        self.trackerThresholdCard.titleLabel.setText(t("tracker_stop_threshold"))
        self.predictionMaxDistanceCard.titleLabel.setText(t("prediction_max_distance_px"))
        self.trackerShowCard.titleLabel.setText(t("tracker_show_prediction"))
