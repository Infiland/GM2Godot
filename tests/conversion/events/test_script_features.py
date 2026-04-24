import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.conversion.script_generator import generate_script_content


class TestScriptFeatures(unittest.TestCase):
    def test_loads_close_button_feature(self):
        content = generate_script_content([{"eventType": 7, "eventNum": 30}])

        self.assertIn("get_tree().auto_accept_quit = false", content)
        self.assertIn("func _notification(what):", content)
        self.assertIn("if what == NOTIFICATION_WM_CLOSE_REQUEST:", content)

    def test_loads_legacy_health_lives_feature(self):
        content = generate_script_content([
            {"eventType": 7, "eventNum": 6},
            {"eventType": 7, "eventNum": 9},
        ])

        self.assertIn("var lives = 0:", content)
        self.assertIn("var health = 100:", content)


if __name__ == "__main__":
    unittest.main()
