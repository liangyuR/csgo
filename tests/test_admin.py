import os
import sys
import importlib.util
import unittest
from unittest import mock


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


ADMIN_PATH = os.path.join(SRC_DIR, "win_utils", "admin.py")
spec = importlib.util.spec_from_file_location("axiom_admin_test_module", ADMIN_PATH)
admin = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(admin)


class AdminTests(unittest.TestCase):
    def setUp(self) -> None:
        admin._ATTEMPTED_FEATURES.clear()

    def test_build_elevated_launch_preserves_args_and_feature_marker(self) -> None:
        with mock.patch.object(admin.sys, "argv", ["src/main.py", "--profile", "dev build"]):
            with mock.patch.object(admin.sys, "executable", r"C:\Python311\python.exe"):
                executable, parameters = admin._build_elevated_launch("ddxoft")

        self.assertEqual(executable, r"C:\Python311\python.exe")
        self.assertIn(os.path.abspath("src/main.py"), parameters)
        self.assertIn("--profile", parameters)
        self.assertIn('"dev build"', parameters)
        self.assertIn("--axiom-admin-relaunch", parameters)
        self.assertIn("--axiom-admin-feature=ddxoft", parameters)

    def test_request_admin_privileges_shell_executes_and_exits_on_success(self) -> None:
        shell32 = mock.Mock()
        shell32.ShellExecuteW.return_value = 42

        with mock.patch.object(admin, "is_admin", return_value=False):
            with mock.patch.object(admin.sys, "argv", ["src/main.py", "--foo"]):
                with mock.patch.object(admin.sys, "executable", r"C:\Python311\python.exe"):
                    with mock.patch.object(admin.ctypes, "windll", mock.Mock(shell32=shell32), create=True):
                        with self.assertRaises(SystemExit):
                            admin.request_admin_privileges("ddxoft")

        call = shell32.ShellExecuteW.call_args
        self.assertIsNotNone(call)
        self.assertEqual(call.args[1], "runas")
        self.assertEqual(call.args[2], r"C:\Python311\python.exe")
        self.assertIn("--axiom-admin-feature=ddxoft", call.args[3])

    def test_request_admin_privileges_failed_launch_is_only_attempted_once_per_feature(self) -> None:
        shell32 = mock.Mock()
        shell32.ShellExecuteW.return_value = 5

        with mock.patch.object(admin, "is_admin", return_value=False):
            with mock.patch.object(admin.sys, "argv", ["src/main.py"]):
                with mock.patch.object(admin.sys, "executable", r"C:\Python311\python.exe"):
                    with mock.patch.object(admin.ctypes, "windll", mock.Mock(shell32=shell32), create=True):
                        self.assertFalse(admin.request_admin_privileges("ddxoft"))
                        self.assertFalse(admin.request_admin_privileges("ddxoft"))

        self.assertEqual(shell32.ShellExecuteW.call_count, 1)

    def test_request_admin_privileges_skips_when_relaunch_marker_present(self) -> None:
        shell32 = mock.Mock()

        with mock.patch.object(admin, "is_admin", return_value=False):
            with mock.patch.object(admin.sys, "argv", ["src/main.py", "--axiom-admin-relaunch"]):
                with mock.patch.object(admin.ctypes, "windll", mock.Mock(shell32=shell32), create=True):
                    self.assertFalse(admin.request_admin_privileges("ddxoft"))

        shell32.ShellExecuteW.assert_not_called()

    def test_ensure_admin_for_feature_short_circuits_when_already_admin(self) -> None:
        with mock.patch.object(admin, "is_admin", return_value=True):
            self.assertTrue(admin.ensure_admin_for_feature("ddxoft"))


if __name__ == "__main__":
    unittest.main()
