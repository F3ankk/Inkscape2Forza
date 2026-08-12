import unittest
from unittest.mock import patch

from inkscape2forza import gamesave, i18n, workflows


class LanguageTests(unittest.TestCase):
    def test_language_selection_is_exclusive(self):
        with patch.object(i18n, "IS_SIMPLIFIED_CHINESE", True):
            self.assertEqual(i18n.tr("中文", "English"), "中文")
        with patch.object(i18n, "IS_SIMPLIFIED_CHINESE", False):
            self.assertEqual(i18n.tr("中文", "English"), "English")


class AccountSelectionTests(unittest.TestCase):
    def setUp(self):
        gamesave._cached_gamesave_dir = None
        gamesave._accounts = {}
        gamesave._selected_account = None

    @patch("inkscape2forza.gamesave.os.listdir", return_value=[
        "u_222_16D460", "not_an_account", "u_111_16D460"
    ])
    @patch("inkscape2forza.gamesave.resolve_gamertags", return_value={"111": "FirstUser"})
    @patch("inkscape2forza.gamesave.os.path.isdir", return_value=True)
    @patch("inkscape2forza.gamesave.os.path.exists", return_value=True)
    def test_account_is_selected_once_and_reused(self, _exists, _isdir, _resolve, _listdir):
        self.assertEqual(
            gamesave.refresh_accounts(),
            ["FirstUser", "222"],
        )
        self.assertTrue(gamesave.select_account("222"))
        with patch("inkscape2forza.gamesave.ui.refresh_accounts"):
            _, user_dir, containers_root = gamesave.choose_containers_root()
        self.assertTrue(user_dir.endswith("u_222_16D460"))
        self.assertTrue(containers_root.endswith("u_222_16D460\\current\\ContainersRoot"))


class BackupTests(unittest.TestCase):
    @patch("inkscape2forza.gamesave.datetime.datetime")
    def test_default_filename_contains_xuid_and_timestamp(self, mocked_datetime):
        mocked_datetime.now.return_value.strftime.return_value = "20260812091011"
        self.assertEqual(
            gamesave.backup_default_filename(r"C:\save\u_2535453461403404_16D460"),
            "backup_2535453461403404_20260812091011.zip",
        )

    def test_backup_is_written_to_selected_path(self):
        user_dir = r"C:\save\u_111_16D460"
        output_path = r"D:\backups\chosen-name.zip"
        with (
            patch("inkscape2forza.gamesave.ui.log"),
            patch("inkscape2forza.gamesave.shutil.make_archive", return_value=output_path) as make_archive,
        ):
            result = gamesave.create_backup(user_dir, output_path)

        self.assertEqual(result, output_path)
        make_archive.assert_called_once_with(r"D:\backups\chosen-name", "zip", user_dir)


class VinylizerOpacityTests(unittest.TestCase):
    def test_zero_threshold_still_ignores_fully_transparent_layers(self):
        self.assertTrue(workflows.json_shape_is_at_or_below_opacity({"color": [1, 2, 3, 0]}, 0))
        self.assertFalse(workflows.json_shape_is_at_or_below_opacity({"color": [1, 2, 3, 1]}, 0))

    def test_threshold_is_inclusive(self):
        self.assertTrue(workflows.json_shape_is_at_or_below_opacity({"color": [1, 2, 3, 64]}, 64))
        self.assertFalse(workflows.json_shape_is_at_or_below_opacity({"color": [1, 2, 3, 65]}, 64))


if __name__ == "__main__":
    unittest.main()
