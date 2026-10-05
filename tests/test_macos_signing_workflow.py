from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/macos-signing-verification.yml"


def step(content: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    begin = content.index(marker)
    end = content.find("\n      - ", begin + len(marker))
    return content[begin:] if end == -1 else content[begin:end]


def policy_errors(content: str) -> tuple[str, ...]:
    errors: list[str] = []
    expected = (
        "on:\n  workflow_dispatch:\n\npermissions:\n  actions: read\n  contents: read\n",
        "github.repository == 'Infiland/GM2Godot' && github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'",
        "environment: macos-developer-id-release",
        "ref: ${{ github.sha }}\n          fetch-depth: 1\n          persist-credentials: false",
        "cancel-in-progress: false",
    )
    if not all(value in content for value in expected):
        errors.append("trusted manual-main/read-only checkout policy")
    forbidden = ("pull_request:", "push:", "contents: write", "actions: write", "id-token:", "release_publisher", "gh release", "refs/tags/")
    input_definition = re.search(r"^[ \t]*['\"]?inputs['\"]?[ \t]*:", content, re.MULTILINE)
    expressions = re.findall(r"\$\{\{(.*?)\}\}", content, re.DOTALL)
    input_reference = any(re.search(r"\binputs\b", expression) for expression in expressions)
    if input_definition is not None or input_reference or any(value in content for value in forbidden):
        errors.append("bootstrap cannot accept arbitrary inputs or publish")
    names = ("Require exact trusted main checkout", "Verify native macOS GUI lifecycle tests", "Select exact-source unsigned producer", "Acquire and reverify original input bytes", "Sign and verify without publication", "Preserve successful verification-only payloads")
    try:
        offsets = [content.index(f"      - name: {name}\n") for name in names]
        if offsets != sorted(offsets):
            errors.append("trusted input/secret/signing order")
        signing = step(content, names[4])
        secrets = re.findall(r"\$\{\{ secrets\.([A-Z0-9_]+) \}\}", content)
        expected_secrets = ["MACOS_DEVELOPER_ID_P12_BASE64", "MACOS_DEVELOPER_ID_P12_PASSWORD", "APPLE_NOTARY_API_KEY_P8_BASE64"]
        if secrets != expected_secrets or any(f"secrets.{name}" not in signing for name in secrets):
            errors.append("credentials must be scoped only to final signing step")
        for stage in names[2:4]:
            if not all(f"--{name} " in step(content, stage) for name in ("native-proof", "dependency-proof", "bootstrap-proof")):
                errors.append("fresh native/dependency output verification missing")
        if "GH_TOKEN:" in signing:
            errors.append("signing must not inherit the acquisition token")
        if "scripts/acquire_macos_signing_inputs.py fetch" not in step(content, names[3]):
            errors.append("owned verified body acquisition missing")
    except ValueError:
        errors.append("mandatory bootstrap stage missing")
    return tuple(errors)


class TestMacosSigningWorkflow(unittest.TestCase):
    def test_caller_input_expressions_and_yaml_keys_do_not_match_module_filenames(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(policy_errors(content), ())
        module = "scripts/acquire_macos_signing_inputs.py"
        self.assertIn(module, content)
        marker = "      PIP_CONFIG_FILE: /dev/null\n"
        self.assertIn(marker, content)
        literal = content.replace(marker, f"      PIP_CONFIG_FILE: ${{{{ '{module}' }}}}\n", 1)
        self.assertEqual(policy_errors(literal), ())
        for expression in (
            "inputs.source_sha", "inputs . source_sha", "inputs['source_sha']", "inputs",
            "github.event.inputs.source_sha", "github . event . inputs [ 'source_sha' ]",
            "github.event['inputs']['source_sha']",
        ):
            with self.subTest(expression=expression):
                changed = content.replace(marker, f"      PIP_CONFIG_FILE: ${{{{\t{expression}\t}}}}\n", 1)
                self.assertIn("bootstrap cannot accept arbitrary inputs or publish", policy_errors(changed))
        for definition in ("inputs:", "inputs \t:", "'inputs':", '"inputs" :'):
            with self.subTest(definition=definition):
                changed = content.replace("  workflow_dispatch:\n", f"  workflow_dispatch:\n    {definition}\n      source_sha:\n        required: true\n", 1)
                self.assertIn("bootstrap cannot accept arbitrary inputs or publish", policy_errors(changed))

    def test_only_manual_main_read_only_verification_has_late_credentials(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(policy_errors(content), ())
        self.assertEqual(content.count("secrets."), 3)
        self.assertNotIn("--run-id", content)
        self.assertNotIn("--artifact-id", content)
        self.assertNotIn("--url", content)
        self.assertIn("timeout-minutes: 180", content)
        self.assertIn("test -z \"$(git status --porcelain=v1 --untracked-files=no)\"", content)
        self.assertNotIn("timeout-minutes:", step(content, "Sign and verify without publication"))
        self.assertIn("python -I scripts/sign_notarize_macos.py", content)
        self.assertIn("python -I scripts/acquire_macos_signing_inputs.py plan", content)
        self.assertIn("python -I scripts/acquire_macos_signing_inputs.py fetch", content)

    def test_pr_fork_checkout_write_or_caller_input_bypasses_fail_policy(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        changes = (
            ("  workflow_dispatch:", "  pull_request:"),
            ("github.repository == 'Infiland/GM2Godot'", "github.repository != 'Infiland/GM2Godot'"),
            ("contents: read", "contents: write"),
            ("ref: ${{ github.sha }}", "ref: ${{ github.event.pull_request.head.sha }}"),
            ("persist-credentials: false", "persist-credentials: true"),
            ("  workflow_dispatch:\n", "  workflow_dispatch:\n    inputs:\n      producer_run:\n        required: true\n"),
        )
        for old, new in changes:
            with self.subTest(change=old):
                self.assertIn(old, content)
                self.assertTrue(policy_errors(content.replace(old, new, 1)))

    def test_scoped_secret_and_verified_input_stage_regressions_fail_policy(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        token = "          MACOS_DEVELOPER_ID_P12_PASSWORD: ${{ secrets.MACOS_DEVELOPER_ID_P12_PASSWORD }}\n"
        earlier = content.replace(token, "", 1).replace("      PIP_CONFIG_FILE: /dev/null\n", "      PIP_CONFIG_FILE: /dev/null\n" + token, 1)
        self.assertTrue(policy_errors(earlier))
        signing = step(content, "Sign and verify without publication")
        without = content.replace(signing, "", 1)
        earlier_signing = without.replace("      - name: Acquire and reverify original input bytes\n", signing + "\n      - name: Acquire and reverify original input bytes\n", 1)
        self.assertTrue(policy_errors(earlier_signing))
        self.assertTrue(policy_errors(content.replace("scripts/acquire_macos_signing_inputs.py fetch", "echo bypass", 1)))
        self.assertTrue(policy_errors(content.replace("--native-proof ", "--unchecked-native ", 1)))

    def test_native_locked_setup_and_verification_namespace_stay_distinct(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("os: macos-26\n", content)
        self.assertIn("os: macos-26-intel\n", content)
        self.assertIn("python-version: '3.12.10'", content)
        self.assertIn("--expected-machine \"${{ matrix.architecture }}\"", content)
        self.assertIn("constraints/requirements-macos-py312.lock", content)
        self.assertIn("--only-binary=:all:", content)
        native = step(content, "Verify native macOS GUI lifecycle tests")
        self.assertIn("python -I tests/test_macos_gui_artifact_verifier.py", native)
        payloads = step(content, "Preserve successful verification-only payloads")
        self.assertIn("-verification-only-${{ github.run_id }}-${{ github.run_attempt }}", payloads)
        self.assertNotIn("if: ${{ always()", payloads)
        self.assertIn("if-no-files-found: error", payloads)
        self.assertNotIn("-signed\n", payloads)

    def test_existing_publisher_still_requires_main_quality_and_run_owned_protocol(self) -> None:
        release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        match = re.search(r"^  release:\n    needs: \[([^\]]+)\]", release, re.MULTILINE)
        self.assertIsNotNone(match)
        if match is None:
            self.fail("publisher needs unavailable")
        needs = {name.strip() for name in match.group(1).split(",")}
        self.assertTrue({"get-version", "release-state-preflight", "build", "main-quality"} <= needs)
        self.assertIn("needs.main-quality.result == 'success'", release)
        self.assertIn("run: python3 scripts/release_publisher.py", release)
        self.assertIn("RELEASE_TARGET_SHA: ${{ github.sha }}", release)


if __name__ == "__main__":
    unittest.main()
