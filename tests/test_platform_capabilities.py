from __future__ import annotations

import unittest
from typing import cast

from src.conversion.platform_capabilities import (
    generate_platform_capability_report,
    iter_platform_capability_checks,
    render_platform_capability_markdown,
)


class TestPlatformCapabilities(unittest.TestCase):
    def test_desktop_target_report_filters_common_and_desktop_checks(self) -> None:
        checks = iter_platform_capability_checks("windows")
        targets = {check.target for check in checks}

        self.assertIn("all", targets)
        self.assertIn("desktop", targets)
        self.assertIn("steam", targets)
        self.assertIn("services", targets)
        self.assertNotIn("android", targets)
        self.assertTrue(
            any("clipboard_set_text" in check.apis for check in checks)
        )

    def test_mobile_report_names_permissions_services_and_export_keys(self) -> None:
        report = generate_platform_capability_report("android")
        checks = cast(list[dict[str, object]], report["checks"])

        self.assertEqual(report["selected_target"], "android")
        self.assertTrue(
            any(
                check["kind"] == "permission"
                and check["capability"] == "microphone"
                and "audio_start_recording" in cast(list[str], check["apis"])
                and "permissions/record_audio"
                in cast(list[str], check["godot_export_keys"])
                for check in checks
            )
        )
        self.assertTrue(
            any(
                check["target"] == "store"
                and check["capability"] == "iap"
                and "iap_activate" in cast(list[str], check["apis"])
                for check in checks
            )
        )
        self.assertTrue(
            any(
                check["target"] == "services"
                and "push_notifications_extension" in cast(list[str], check["apis"])
                for check in checks
            )
        )

    def test_all_target_report_covers_plugin_and_unsupported_surfaces(self) -> None:
        report = generate_platform_capability_report()
        checks = cast(list[dict[str, object]], report["checks"])

        self.assertEqual(report["issue_number"], 606)
        self.assertTrue(
            any(
                check["target"] == "steam"
                and check["status"] == "requires_plugin"
                and "steam_set_achievement" in cast(list[str], check["apis"])
                for check in checks
            )
        )
        self.assertTrue(
            any(
                check["capability"] == "motion_sensors"
                and check["status"] == "requires_permission"
                and "device_get_tilt_x" in cast(list[str], check["apis"])
                for check in checks
            )
        )

    def test_markdown_report_includes_selected_target(self) -> None:
        markdown = render_platform_capability_markdown("web")

        self.assertIn("Selected target: `web`", markdown)
        self.assertIn("browser_bridge", markdown)
        self.assertIn("html5_dom_cors", markdown)


if __name__ == "__main__":
    unittest.main()
