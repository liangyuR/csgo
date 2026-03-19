from PyQt6.QtCore import QThread, pyqtSignal


def parse_version(v_str):
    """Parse a version string such as 'v1.0.2' into a tuple."""
    v_str = v_str.lower().strip()
    if v_str.startswith("v"):
        v_str = v_str[1:]

    parts = []
    for part in v_str.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts)


class UpdateChecker(QThread):
    """Disabled update checker retained for compatibility."""

    update_available = pyqtSignal(str, str, str)
    up_to_date = pyqtSignal()
    check_failed = pyqtSignal(str)

    def run(self):
        self.up_to_date.emit()


def open_update_url(url):
    """Online update links are disabled in this fork."""
    return None
