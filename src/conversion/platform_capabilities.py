from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, TypeAlias

PlatformCapabilityKind: TypeAlias = Literal[
    "export_preset",
    "permission",
    "plugin",
    "runtime",
]
PlatformCapabilityStatus: TypeAlias = Literal[
    "reported",
    "requires_export_preset",
    "requires_permission",
    "requires_plugin",
    "unsupported",
]


@dataclass(frozen=True)
class PlatformCapabilityCheck:
    target: str
    kind: PlatformCapabilityKind
    capability: str
    status: PlatformCapabilityStatus
    apis: tuple[str, ...]
    godot_export_keys: tuple[str, ...]
    gm2godot_surface: str
    check: str
    recommendation: str
    issue_number: int = 606

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "kind": self.kind,
            "capability": self.capability,
            "status": self.status,
            "apis": list(self.apis),
            "godot_export_keys": list(self.godot_export_keys),
            "gm2godot_surface": self.gm2godot_surface,
            "check": self.check,
            "recommendation": self.recommendation,
            "issue_number": self.issue_number,
        }


_DESKTOP_TARGETS = ("windows", "macos", "linux")

_CAPABILITY_CHECKS: tuple[PlatformCapabilityCheck, ...] = (
    PlatformCapabilityCheck(
        target="all",
        kind="runtime",
        capability="os_debug_gc",
        status="reported",
        apis=(
            "os_type",
            "os_get_info",
            "show_debug_message_ext",
            "gc_collect",
            "weak_ref_alive",
        ),
        godot_export_keys=(),
        gm2godot_surface="GMRuntime OS/debug/GC helpers and gml_api_compatibility.md",
        check="Verify generated compatibility reports list OS/debug/GC APIs as implemented, partial, planned, or unsupported.",
        recommendation="Use conversion diagnostics for unsupported OS/compiler APIs instead of leaving unresolved GML calls.",
    ),
    PlatformCapabilityCheck(
        target="all",
        kind="runtime",
        capability="video_playback",
        status="reported",
        apis=(
            "video_open",
            "video_draw",
            "video_get_status",
            "video_close",
        ),
        godot_export_keys=(),
        gm2godot_surface="GMRuntime video compatibility state and video_runtime_diagnostics",
        check="Report unsupported camera or non-Godot VideoStream sources at runtime.",
        recommendation="Use Ogg Theora or provide a GDExtension-backed VideoStream for formats not handled by Godot.",
    ),
    PlatformCapabilityCheck(
        target="web",
        kind="export_preset",
        capability="browser_bridge",
        status="requires_export_preset",
        apis=(
            "browser_width",
            "browser_height",
            "browser_input_capture",
            "url_get_domain",
            "url_open",
            "url_open_ext",
            "url_open_full",
            "webgl_enabled",
        ),
        godot_export_keys=("html/export_icon", "html/canvas_resize_policy"),
        gm2godot_surface="GMRuntime web platform hook",
        check="Web exports need a browser bridge hook when GameMaker code depends on DOM, window target, or canvas policy.",
        recommendation="Register a web platform service hook or keep the deterministic desktop fallbacks documented in the compatibility report.",
    ),
    PlatformCapabilityCheck(
        target="web",
        kind="plugin",
        capability="html5_dom_cors",
        status="requires_plugin",
        apis=(
            "clickable_add",
            "clickable_add_ext",
            "analytics_event",
            "analytics_event_ext",
            "http_get_request_crossorigin",
            "http_set_request_crossorigin",
        ),
        godot_export_keys=("html/head_include",),
        gm2godot_surface="GMRuntime platform service hook: web",
        check="HTML5 DOM, analytics, and CORS helpers need project-specific JavaScript bridge code.",
        recommendation="Map these APIs through an extension function mapping or register a reviewed web hook.",
    ),
    PlatformCapabilityCheck(
        target="android",
        kind="permission",
        capability="microphone",
        status="requires_permission",
        apis=("audio_start_recording", "audio_get_recorder_count"),
        godot_export_keys=("permissions/record_audio",),
        gm2godot_surface="GMAudio diagnostics and async audio recording payload",
        check="Microphone capture requires an Android export permission plus project AudioEffectCapture setup.",
        recommendation="Enable RECORD_AUDIO in the export preset and provide a capture bus before relying on recording data.",
    ),
    PlatformCapabilityCheck(
        target="ios",
        kind="permission",
        capability="microphone",
        status="requires_permission",
        apis=("audio_start_recording", "audio_get_recorder_count"),
        godot_export_keys=("privacy/microphone_usage_description",),
        gm2godot_surface="GMAudio diagnostics and async audio recording payload",
        check="Microphone capture requires an iOS privacy usage string and project AudioEffectCapture setup.",
        recommendation="Set the iOS microphone usage description and provide a capture bus before relying on recording data.",
    ),
    PlatformCapabilityCheck(
        target="mobile",
        kind="permission",
        capability="camera",
        status="requires_permission",
        apis=("video_open", "os_check_permission", "os_request_permission"),
        godot_export_keys=(
            "permissions/camera",
            "privacy/camera_usage_description",
        ),
        gm2godot_surface="GMRuntime video diagnostics",
        check="Camera-backed video sources require a target camera permission and a capture bridge.",
        recommendation="Provide a platform capture plugin and route camera permissions through project export settings.",
    ),
    PlatformCapabilityCheck(
        target="mobile",
        kind="permission",
        capability="motion_sensors",
        status="requires_permission",
        apis=(
            "device_get_tilt_x",
            "device_get_tilt_y",
            "device_get_tilt_z",
            "os_check_permission",
            "os_request_permission",
        ),
        godot_export_keys=(
            "permissions/access_fine_location",
            "privacy/motion_usage_description",
        ),
        gm2godot_surface="GML API compatibility diagnostics",
        check="Device sensor APIs are rejected unless a target sensor bridge and permissions are supplied.",
        recommendation="Replace unsupported sensor calls or provide a platform plugin that exposes equivalent data.",
    ),
    PlatformCapabilityCheck(
        target="desktop",
        kind="runtime",
        capability="clipboard_url_shell",
        status="reported",
        apis=(
            "clipboard_has_text",
            "clipboard_get_text",
            "clipboard_set_text",
            "url_open",
            "url_open_ext",
            "url_open_full",
        ),
        godot_export_keys=(),
        gm2godot_surface="DisplayServer clipboard and OS.shell_open fallbacks",
        check="Desktop clipboard and URL helpers use Godot runtime services and report fallback limitations.",
        recommendation="Review conversion diagnostics for targets without native clipboard or shell-open support.",
    ),
    PlatformCapabilityCheck(
        target="steam",
        kind="plugin",
        capability="steam_sdk",
        status="requires_plugin",
        apis=(
            "steam_is_initialized",
            "steam_set_achievement",
            "steam_get_achievement",
            "steam_upload_score",
            "steam_download_scores",
        ),
        godot_export_keys=(),
        gm2godot_surface="GMRuntime platform service hook: steam",
        check="Steam APIs require a Godot Steam addon or GDExtension hook.",
        recommendation="Register a Steam platform hook so async Steam results are dispatched through GMAsync.",
    ),
    PlatformCapabilityCheck(
        target="store",
        kind="plugin",
        capability="iap",
        status="requires_plugin",
        apis=(
            "iap_activate",
            "iap_acquire",
            "iap_consume",
            "iap_restore_all",
        ),
        godot_export_keys=("permissions/billing",),
        gm2godot_surface="GMRuntime platform service hook: iap",
        check="In-app purchase APIs require a store billing plugin and export entitlement setup.",
        recommendation="Register an IAP hook that returns GMAsync in_app_purchase payloads for purchase lifecycle events.",
    ),
    PlatformCapabilityCheck(
        target="services",
        kind="plugin",
        capability="cloud_push_ads_analytics",
        status="requires_plugin",
        apis=(
            "cloud_synchronise",
            "cloud_string_save",
            "cloud_file_save",
            "push_notifications_extension",
            "analytics_event",
            "analytics_event_ext",
        ),
        godot_export_keys=("permissions/post_notifications",),
        gm2godot_surface="GMRuntime platform service and extension async hooks",
        check="Cloud, push notification, ads, and analytics behavior is extension-backed.",
        recommendation="Use extension mappings plus async schema registration so callbacks route through GMAsync.",
    ),
    PlatformCapabilityCheck(
        target="uwp_xbox",
        kind="plugin",
        capability="xboxlive",
        status="requires_plugin",
        apis=(
            "xboxlive_user_is_signed_in",
            "xboxlive_achievements_set_progress",
            "xboxlive_stats_get_leaderboard",
            "xboxlive_matchmaking_create",
        ),
        godot_export_keys=("xbox/services_config_id", "xbox/title_id"),
        gm2godot_surface="GMRuntime platform service hook: xboxlive",
        check="Xbox Live and UWP APIs require closed platform SDK access and export runner integration.",
        recommendation="Register an Xbox Live hook for account, achievement, leaderboard, and matchmaking payloads.",
    ),
    PlatformCapabilityCheck(
        target="live_wallpaper",
        kind="plugin",
        capability="wallpaper",
        status="requires_plugin",
        apis=("wallpaper_set_config", "wallpaper_set_subscriptions"),
        godot_export_keys=("android/package/use_custom_build",),
        gm2godot_surface="GMRuntime platform service hook: wallpaper",
        check="Live wallpaper APIs require the Android live wallpaper companion integration.",
        recommendation="Provide a wallpaper hook and use generated async wallpaper event handlers for callbacks.",
    ),
)


def iter_platform_capability_checks(
    target_platform: str | None = None,
) -> tuple[PlatformCapabilityCheck, ...]:
    if target_platform is None:
        return _CAPABILITY_CHECKS

    target = target_platform.casefold()
    aliases = _target_aliases(target)
    return tuple(check for check in _CAPABILITY_CHECKS if check.target in aliases)


def generate_platform_capability_report(
    target_platform: str | None = None,
) -> dict[str, object]:
    checks = iter_platform_capability_checks(target_platform)
    return {
        "report": "platform_capability_report",
        "version": 1,
        "issue_number": 606,
        "selected_target": target_platform,
        "summary": {
            "total": len(checks),
            "by_target": _count_values(check.target for check in checks),
            "by_kind": _count_values(check.kind for check in checks),
            "by_status": _count_values(check.status for check in checks),
        },
        "checks": [check.to_dict() for check in checks],
    }


def render_platform_capability_markdown(
    target_platform: str | None = None,
) -> str:
    checks = iter_platform_capability_checks(target_platform)
    target_label = target_platform or "all targets"
    lines = [
        "# Platform Capability Report",
        "",
        f"Selected target: `{target_label}`",
        "",
        "| Target | Kind | Capability | Status | APIs | Check |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for check in checks:
        lines.append(
            f"| {check.target} | {check.kind} | {check.capability} | {check.status} | "
            f"{', '.join(check.apis)} | {check.check} |"
        )
    return "\n".join(lines) + "\n"


def _target_aliases(target: str) -> set[str]:
    aliases = {"all", target}
    if target in _DESKTOP_TARGETS:
        aliases.add("desktop")
        aliases.add("services")
        aliases.add("steam")
        aliases.add("store")
    if target in {"android", "ios"}:
        aliases.add("mobile")
        aliases.add("store")
        aliases.add("services")
    if target == "web":
        aliases.add("services")
    return aliases


def _count_values(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts
