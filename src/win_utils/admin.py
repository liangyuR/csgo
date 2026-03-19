"""Windows administrator privilege helpers."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

_ELEVATED_RELAUNCH_FLAG = "--axiom-admin-relaunch"
_ELEVATED_FEATURE_PREFIX = "--axiom-admin-feature="
_ATTEMPTED_FEATURES: set[str] = set()


def is_admin() -> bool:
    """Return whether the current process is running with admin privileges."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _is_relaunch_marker_present(argv: list[str] | None = None) -> bool:
    args = list(sys.argv if argv is None else argv)
    return _ELEVATED_RELAUNCH_FLAG in args


def _filter_internal_args(argv: list[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    filtered: list[str] = []
    for arg in args:
        if arg == _ELEVATED_RELAUNCH_FLAG:
            continue
        if arg.startswith(_ELEVATED_FEATURE_PREFIX):
            continue
        filtered.append(arg)
    return filtered


def _build_elevated_launch(feature_name: str) -> tuple[str, str]:
    base_args = _filter_internal_args()

    if getattr(sys, "frozen", False):
        executable = sys.executable
        argv = base_args
    else:
        executable = sys.executable
        script_path = os.path.abspath(sys.argv[0])
        argv = [script_path, *base_args]

    if _ELEVATED_RELAUNCH_FLAG not in argv:
        argv.append(_ELEVATED_RELAUNCH_FLAG)
    argv.append(f"{_ELEVATED_FEATURE_PREFIX}{feature_name}")

    return executable, subprocess.list2cmdline(argv)


def request_admin_privileges(feature_name: str = "application") -> bool:
    """Request admin privileges by relaunching the current process elevated."""
    if is_admin():
        return True

    if "--no-admin" in sys.argv:
        return False

    if _is_relaunch_marker_present():
        return False

    normalized_feature = (feature_name or "application").strip() or "application"
    if normalized_feature in _ATTEMPTED_FEATURES:
        return False
    _ATTEMPTED_FEATURES.add(normalized_feature)

    try:
        executable, parameters = _build_elevated_launch(normalized_feature)
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            None,
            1,
        )
        if result > 32:
            sys.exit(0)
        return False
    except Exception:
        return False


def ensure_admin_for_feature(feature_name: str, reason: str | None = None) -> bool:
    """Ensure admin privileges are available for a specific feature."""
    if is_admin():
        return True

    if reason:
        print(f"[Admin] {reason}")
    return request_admin_privileges(feature_name)


def check_and_request_admin() -> bool:
    """Compatibility wrapper that now only reports admin status."""
    return is_admin()
