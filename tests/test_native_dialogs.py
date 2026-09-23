from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from archeon.ui import native_dialogs


class NativeDialogTests(unittest.TestCase):
    @patch("archeon.ui.native_dialogs.subprocess.run")
    def test_windows_picker_decodes_one_or_many_paths(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, '["C:\\\\a.mp3","D:\\\\b.wav"]\n', "")
        with patch("archeon.ui.native_dialogs.os.name", "nt"):
            selected = native_dialogs.choose_audio_files()
        self.assertEqual(selected, ["C:\\a.mp3", "D:\\b.wav"])
        arguments = run.call_args.args[0]
        self.assertIn("-STA", arguments)
        self.assertNotIn("tkinter", native_dialogs.__dict__)

    @patch("archeon.ui.native_dialogs.subprocess.run")
    def test_cancel_returns_empty_result(self, run) -> None:
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        with patch("archeon.ui.native_dialogs.os.name", "nt"):
            self.assertIsNone(native_dialogs.choose_visual_file("logo"))

    def test_visual_kind_is_validated_before_opening_dialog(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_visual_kind"):
            native_dialogs.choose_visual_file("executable")


if __name__ == "__main__":
    unittest.main()
