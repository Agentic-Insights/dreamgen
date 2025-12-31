import unittest
from unittest.mock import MagicMock, patch

# It's important to be able to import ArtStyle and ArtStylePlugin
# This might require adjusting sys.path if tests are run from the root
# or ensuring the src directory is correctly recognized.
# Assuming 'src' is in PYTHONPATH or tests are run in a way that src is importable:
from src.plugins.art_style import ArtStyle, ArtStylePlugin, get_art_style


class TestArtStylePlugin(unittest.TestCase):

    def setUp(self):
        # Reset singleton instance or its state for each test
        # One way: set _instance to None, so __new__ runs again.
        # Or, get the instance and manually reset its state.
        ArtStylePlugin._instance = None  # Force re-creation for a clean state
        self.plugin = ArtStylePlugin()
        # Prevent actual file loading during unit tests
        self.plugin._load_styles = MagicMock()
        self.plugin._styles = []
        self.plugin._last_style = None

    def test_get_random_style_no_styles(self):
        self.plugin._styles = []
        self.assertIsNone(self.plugin.get_random_style())

    def test_get_random_style_one_style(self):
        style1 = ArtStyle("Style1", "Desc1")
        self.plugin._styles = [style1]

        # Test with avoid_last=False
        self.assertEqual(self.plugin.get_random_style(avoid_last=False), style1)
        self.assertEqual(self.plugin._last_style, style1)

        # Test with avoid_last=True (should still return the only style)
        self.plugin._last_style = style1  # Simulate it was chosen before
        self.assertEqual(self.plugin.get_random_style(avoid_last=True), style1)
        self.assertEqual(self.plugin._last_style, style1)

    def test_get_random_style_two_styles_avoid_last(self):
        style1 = ArtStyle("Style1", "Desc1")
        style2 = ArtStyle("Style2", "Desc2")
        self.plugin._styles = [style1, style2]

        # Set last style to style1
        self.plugin._last_style = style1
        # Next call with avoid_last=True should return style2
        self.assertEqual(self.plugin.get_random_style(avoid_last=True), style2)
        self.assertEqual(self.plugin._last_style, style2)

        # Set last style to style2
        self.plugin._last_style = style2
        # Next call with avoid_last=True should return style1
        self.assertEqual(self.plugin.get_random_style(avoid_last=True), style1)
        self.assertEqual(self.plugin._last_style, style1)

    def test_get_random_style_multiple_styles_no_avoid_last(self):
        style1 = ArtStyle("Style1", "Desc1")
        style2 = ArtStyle("Style2", "Desc2")
        self.plugin._styles = [style1, style2]

        # Mock random.choice to control the outcome
        with patch("random.choice", return_value=style1) as mock_choice:
            chosen_style = self.plugin.get_random_style(avoid_last=False)
            self.assertEqual(chosen_style, style1)
            mock_choice.assert_called_once_with([style1, style2])
            self.assertEqual(self.plugin._last_style, style1)

    def test_get_art_style_integration(self):
        # Test the helper function get_art_style
        style1 = ArtStyle("Fancy", "Very Fancy")
        self.plugin._styles = [style1]

        returned_string = get_art_style()
        self.assertEqual(returned_string, "in the style of Fancy (Very Fancy)")

        self.plugin._styles = []
        returned_string_empty = get_art_style()
        self.assertEqual(returned_string_empty, "")


if __name__ == "__main__":
    unittest.main()
