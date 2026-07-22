from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from apw import cli
from apw.lifecycle import LifecycleError


class ChooseVaultTests(unittest.TestCase):
    def test_dialog_returns_valid_directory(self) -> None:
        with TemporaryDirectory() as temp:
            vault = Path(temp)
            with (
                mock.patch("apw.cli.choose_one", return_value="dialog"),
                mock.patch("apw.cli.pick_directory", return_value=vault),
            ):
                self.assertEqual(cli.choose_vault(Path(temp)), vault)

    def test_dialog_cancel_falls_back_to_manual(self) -> None:
        with TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            vault.mkdir()
            with (
                mock.patch("apw.cli.choose_one", return_value="dialog"),
                mock.patch("apw.cli.pick_directory", return_value=None),
                mock.patch("apw.cli.prompt", return_value=str(vault)),
            ):
                self.assertEqual(cli.choose_vault(Path(temp)), vault)

    def test_manual_input_validates_directory(self) -> None:
        with TemporaryDirectory() as temp:
            vault = Path(temp) / "vault"
            vault.mkdir()
            with (
                mock.patch("apw.cli.choose_one", return_value="manual"),
                mock.patch("apw.cli.prompt", return_value=str(vault)),
            ):
                self.assertEqual(cli.choose_vault(Path(temp)), vault)

    def test_manual_input_nonexistent_raises(self) -> None:
        with (
            mock.patch("apw.cli.choose_one", return_value="manual"),
            mock.patch("apw.cli.prompt", return_value=str(Path("/no/such/vault"))),
        ):
            with self.assertRaises(LifecycleError):
                cli.choose_vault(Path("/no/such/home"))

    def test_dialog_nonexistent_raises(self) -> None:
        with (
            mock.patch("apw.cli.choose_one", return_value="dialog"),
            mock.patch("apw.cli.pick_directory", return_value=Path("/no/such/vault")),
        ):
            with self.assertRaises(LifecycleError):
                cli.choose_vault(Path("/no/such/home"))


if __name__ == "__main__":
    unittest.main()
