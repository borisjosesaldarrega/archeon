from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from archeon.system.startup import RUN_KEY, VALUE_NAME, configure_launch_at_login, launch_command


@unittest.skipUnless(os.name == "nt", "Windows startup integration")
class StartupIntegrationTests(unittest.TestCase):
    def test_development_command_uses_module_entrypoint(self) -> None:
        command = launch_command()
        self.assertIn(" -m archeon", command)
        self.assertTrue(command.startswith('"'))

    def test_launch_at_login_writes_and_removes_only_current_user_value(self) -> None:
        key = MagicMock()
        key.__enter__.return_value = key
        with (
            patch("winreg.CreateKeyEx", return_value=key) as create_key,
            patch("winreg.SetValueEx") as set_value,
            patch("winreg.DeleteValue") as delete_value,
        ):
            configure_launch_at_login(True)
            create_key.assert_called_once()
            self.assertEqual(create_key.call_args.args[1], RUN_KEY)
            set_value.assert_called_once()
            self.assertEqual(set_value.call_args.args[1], VALUE_NAME)

            configure_launch_at_login(False)
            delete_value.assert_called_once_with(key, VALUE_NAME)


if __name__ == "__main__":
    unittest.main()
