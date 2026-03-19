"""Arduino board definition spoofing helpers."""

from __future__ import annotations

import glob
import os
import shutil

import serial.tools.list_ports

from .admin import ensure_admin_for_feature

_TARGET_VID = 0x046D
_TARGET_PID = 0xC07D
_ARDUINO_VID = 0x2341
_ARDUINO_PID = 0x8036


def find_boards_txt() -> str | None:
    """Locate the active Arduino AVR board definition file."""
    possible_paths: list[str] = []

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        pattern = os.path.join(
            local_appdata,
            r"Arduino15\packages\arduino\hardware\avr\*\boards.txt",
        )
        possible_paths.extend(sorted(glob.glob(pattern), reverse=True))

    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    possible_paths.append(os.path.join(program_files_x86, r"Arduino\hardware\arduino\avr\boards.txt"))
    possible_paths.append(os.path.join(program_files, r"Arduino\hardware\arduino\avr\boards.txt"))

    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None


def spoof_arduino_board() -> tuple[bool, str]:
    """Update Arduino Leonardo USB IDs to mimic a Logitech mouse."""
    if not ensure_admin_for_feature(
        "arduino_spoof",
        reason="Arduino device spoofing needs administrator privileges to edit board definitions.",
    ):
        raise PermissionError("Administrator privileges are required to spoof the Arduino board.")

    boards_file = find_boards_txt()
    if not boards_file:
        raise FileNotFoundError(
            "boards.txt was not found. Make sure Arduino IDE and the AVR board package are installed."
        )

    backup_file = boards_file + ".bak"
    if not os.path.exists(backup_file):
        shutil.copy2(boards_file, backup_file)

    try:
        with open(boards_file, "r", encoding="utf-8") as file:
            lines = file.readlines()

        new_lines: list[str] = []
        spoofed = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("leonardo.build.vid="):
                new_lines.append("leonardo.build.vid=0x046D\n")
                spoofed = True
                continue
            if stripped.startswith("leonardo.build.pid="):
                new_lines.append("leonardo.build.pid=0xC07D\n")
                spoofed = True
                continue
            if stripped.startswith("leonardo.build.usb_product="):
                new_lines.append('leonardo.build.usb_product="Logitech G502 HERO Gaming Mouse"\n')
                spoofed = True
                continue
            new_lines.append(line)

        with open(boards_file, "w", encoding="utf-8") as file:
            file.writelines(new_lines)

        return spoofed, boards_file
    except Exception:
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, boards_file)
        raise


def verify_spoof(specific_port: str | None = None) -> tuple[bool, str]:
    """Check whether the connected device is using the spoofed IDs."""
    ports = serial.tools.list_ports.comports()
    if specific_port:
        ports = [port for port in ports if port.device == specific_port]

    spoofed_device = None
    original_device = None
    for port in ports:
        if port.vid == _TARGET_VID and port.pid == _TARGET_PID:
            spoofed_device = port
            break
        if port.vid == _ARDUINO_VID and port.pid == _ARDUINO_PID:
            original_device = port

    if spoofed_device is not None:
        return (
            True,
            (
                f"Spoofed device detected on {spoofed_device.device}\n"
                f"Name: {spoofed_device.description or 'Logitech G502 HERO'}\n"
                f"VID: {spoofed_device.vid:04X} PID: {spoofed_device.pid:04X}"
            ),
        )

    if original_device is not None:
        return (
            False,
            (
                f"Original Arduino device detected on {original_device.device}\n"
                f"Name: {original_device.description}\n"
                f"VID: {original_device.vid:04X} PID: {original_device.pid:04X}\n\n"
                "Reflash the board after spoofing to apply the new USB identity."
            ),
        )

    return False, "No matching Arduino device was detected."
