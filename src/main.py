"""Application entrypoint."""

from __future__ import annotations

import os
import queue
import sys
import threading
from typing import Optional

if sys.platform == "win32":
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

if sys.platform == "win32":
    import ctypes

    try:
        _PM_V2 = ctypes.c_void_p(-4)
        if not ctypes.windll.user32.SetProcessDpiAwarenessContext(_PM_V2):
            raise OSError("SetProcessDpiAwarenessContext returned FALSE")
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

src_dir = os.path.dirname(os.path.abspath(__file__))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from core.logging_config import setup_logging
from version import __version__

logger = setup_logging("INFO")
logger.info("Axiom v%s Starting...", __version__)

project_root = os.path.dirname(src_dir)

import pywintypes  # noqa: F401

from core.ai_loop import ai_logic_loop
from core.auto_fire import auto_fire_loop
from core.config import Config, apply_model_constraints, load_config, save_config
from core.control_loop import control_loop
from core.detection_state import LatestDetectionState
from core.key_listener import aim_toggle_key_listener
from core.model_registry import get_model_spec
from core.ultralytics_runtime import UltralyticsEngineModel
from gui.disclaimer_dialog import DisclaimerDialog
from gui.overlay import PyQtOverlay
from gui.status_panel import StatusPanel
detect_thread: Optional[threading.Thread] = None
control_thread: Optional[threading.Thread] = None
auto_fire_thread: Optional[threading.Thread] = None


def _stop_ai_threads(config: Config) -> None:
    global detect_thread, control_thread, auto_fire_thread

    if not any(
        thread is not None and thread.is_alive()
        for thread in (detect_thread, control_thread, auto_fire_thread)
    ):
        return

    config.Running = False
    if detect_thread is not None:
        detect_thread.join()
    if control_thread is not None:
        control_thread.join()
    if auto_fire_thread is not None:
        auto_fire_thread.join()


def _resolve_model_runtime_inputs(config: Config, model_id: str) -> tuple[object, str] | tuple[None, None]:
    model_spec = get_model_spec(model_id)
    if model_spec is None:
        logger.error("Unknown model id: %s", model_id)
        return None, None

    config.model_id = model_spec.model_id
    config.model_path = model_spec.engine_path
    config.model_input_size = model_spec.input_size
    apply_model_constraints(config)

    model_path = model_spec.engine_path
    if not os.path.isabs(model_path):
        model_path = os.path.join(project_root, model_path)

    if not model_path.endswith(".engine"):
        logger.error("Only TensorRT .engine runtime is supported: %s", model_path)
        return None, None
    if not os.path.exists(model_path):
        logger.error("Model file does not exist: %s", model_path)
        return None, None

    return model_spec, model_path


def _load_ultralytics_model(config: Config, model_id: str):
    model_spec, model_path = _resolve_model_runtime_inputs(config, model_id)
    if model_spec is None or model_path is None:
        return None, None

    model = UltralyticsEngineModel(model_path, input_size=model_spec.input_size)
    config.current_provider = model.provider_name
    config.model_id = model_spec.model_id
    config.model_path = model_spec.engine_path
    config.model_input_size = model_spec.input_size
    logger.info("Loaded model %s with provider %s", model_spec.display_name, config.current_provider)
    return model_spec, model


def start_ai_threads(
    config: Config,
    overlay_queue: queue.Queue,
    auto_fire_boxes_queue: queue.Queue,
    model_id: str,
    preloaded_model_spec=None,
    preloaded_model=None,
) -> bool:
    global detect_thread, control_thread, auto_fire_thread

    _stop_ai_threads(config)

    config.Running = True

    try:
        if (
            preloaded_model_spec is not None
            and preloaded_model is not None
            and getattr(preloaded_model_spec, "model_id", None) == model_id
        ):
            model_spec = preloaded_model_spec
            model = preloaded_model
        else:
            model_spec, model = _load_ultralytics_model(config, model_id)
            if model_spec is None or model is None:
                return False
    except Exception as e:
        logger.exception("Failed to load Ultralytics TensorRT engine")
        logger.error(
            "Ultralytics TensorRT inference is required. Install 'ultralytics', ensure TensorRT/CUDA dependencies are available, and place a valid .engine file in the Model directory."
        )
        return False

    latest_detection_state = LatestDetectionState()

    detect_thread = threading.Thread(
        target=ai_logic_loop,
        args=(config, model, model_spec, overlay_queue, latest_detection_state, auto_fire_boxes_queue),
        daemon=True,
    )
    control_thread = threading.Thread(
        target=control_loop,
        args=(config, latest_detection_state),
        daemon=True,
    )
    auto_fire_thread = threading.Thread(
        target=auto_fire_loop,
        args=(config, auto_fire_boxes_queue),
        daemon=True,
    )
    detect_thread.start()
    control_thread.start()
    auto_fire_thread.start()
    return True


def main():
    config = Config()
    load_config(config)
    logger.info("Loaded config mouse move method: %s", config.mouse_move_method)

    if config.mouse_move_method == "ddxoft":
        try:
            from win_utils.ddxoft_mouse import ensure_ddxoft_ready, test_ddxoft_functions

            if ensure_ddxoft_ready():
                test_ddxoft_functions()
            else:
                logger.warning("ddxoft init failed, falling back to mouse_event")
                config.mouse_move_method = "mouse_event"
                config.mouse_click_method = "mouse_event"
        except Exception as e:
            logger.warning("ddxoft init raised exception, falling back to mouse_event: %s", e)
            config.mouse_move_method = "mouse_event"
            config.mouse_click_method = "mouse_event"

    overlay_queue: queue.Queue = queue.Queue(maxsize=config.max_queue_size)
    auto_fire_boxes_queue: queue.Queue = queue.Queue(maxsize=config.max_queue_size)
    preloaded_model_spec = None
    preloaded_model = None

    if config.model_id:
        try:
            preloaded_model_spec, preloaded_model = _load_ultralytics_model(config, config.model_id)
        except Exception:
            logger.exception("Failed to preload Ultralytics TensorRT engine before QApplication startup")
            logger.error(
                "Ultralytics TensorRT inference is required. Install 'ultralytics', ensure TensorRT/CUDA dependencies are available, and place a valid .engine file in the Model directory."
            )

    def start_threads_callback(model_id: str) -> bool:
        nonlocal preloaded_model_spec, preloaded_model
        use_spec = preloaded_model_spec if getattr(preloaded_model_spec, "model_id", None) == model_id else None
        use_model = preloaded_model if use_spec is not None else None
        started = start_ai_threads(
            config,
            overlay_queue,
            auto_fire_boxes_queue,
            model_id,
            preloaded_model_spec=use_spec,
            preloaded_model=use_model,
        )
        if started and use_model is not None:
            preloaded_model_spec = None
            preloaded_model = None
        return started

    toggle_thread = threading.Thread(target=aim_toggle_key_listener, args=(config,), daemon=True)
    toggle_thread.start()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    app = QApplication(sys.argv)

    if not config.disclaimer_agreed:
        disclaimer = DisclaimerDialog()
        if disclaimer.exec() == 1:
            config.disclaimer_agreed = True
            save_config(config)
        else:
            sys.exit(0)

    if not config.first_run_complete:
        from gui.fluent_app.setup_wizard import SetupWizard

        wizard = SetupWizard(config)
        wizard.exec()
        wizard.applyChosenTheme()
        config.first_run_complete = True
        save_config(config)

    main_overlay = PyQtOverlay(overlay_queue, config)
    main_overlay.show()

    status_panel = StatusPanel(config)
    if config.show_status_panel:
        status_panel.show()
    else:
        status_panel.hide()

    from win_utils.console import hide_console, show_console

    if config.show_console:
        show_console()
    else:
        hide_console()

    from core.config_manager import ConfigManager
    from gui.fluent_app.window import AxiomWindow

    settings_window = AxiomWindow()
    settings_window.setConfig(config)
    settings_window.setConfigManager(ConfigManager())
    settings_window.show()

    if config.model_id and not start_threads_callback(config.model_id):
        logger.warning("AI thread startup failed, please check model configuration")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
