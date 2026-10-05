"""Trusted-main Developer ID CLI with explicit purpose; never publishes assets."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

if (source_root := str(Path(__file__).resolve().parents[1])) not in sys.path:
    sys.path.insert(0, source_root)

from scripts.macos_signing import (
    Architecture,
    MetadataRequest,
    SigningFailure,
    SigningOptions,
    SigningPurpose,
    metadata_worker,
    safe_failure_message,
    sign_publication,
    sign_verification,
)


class SigningArguments(argparse.Namespace):
    purpose: SigningPurpose
    context: Path
    source_root: Path
    unsigned_zip: Path
    unsigned_dmg: Path
    architecture: Architecture
    output_root: Path
    proof_root: Path


class MetadataArguments(argparse.Namespace):
    purpose: SigningPurpose
    context: Path
    source_root: Path
    app: Path
    zip: Path
    dmg: Path


def metadata_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Scrubbed maintained artifact verification worker")
    parser.add_argument("--purpose", default="verification_only", choices=("verification_only", "publication"))
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--dmg", required=True, type=Path)
    args = parser.parse_args(argv, namespace=MetadataArguments())
    request = MetadataRequest(args.context, args.source_root, args.app, args.zip, args.dmg, args.purpose)
    try:
        result = metadata_worker(request, entry_script=Path(__file__))
    except (SigningFailure, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as error:
        print(safe_failure_message(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def main(argv: list[str] | None = None) -> int:
    actual = sys.argv[1:] if argv is None else argv
    if actual and actual[0] == "--metadata-worker":
        return metadata_main(actual[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purpose", default="verification_only", choices=("verification_only", "publication"))
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--unsigned-zip", required=True, type=Path)
    parser.add_argument("--unsigned-dmg", required=True, type=Path)
    parser.add_argument("--architecture", required=True, choices=("arm64", "x86_64"))
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--proof-root", required=True, type=Path)
    args = parser.parse_args(actual, namespace=SigningArguments())
    options = SigningOptions(args.context, args.source_root, args.unsigned_zip, args.unsigned_dmg, args.architecture, args.output_root, args.proof_root, args.purpose)
    try:
        if args.purpose == "publication":
            result = sign_publication(options)
        else:
            result = sign_verification(options)
    except (SigningFailure, OSError, ValueError, KeyError, TypeError, RecursionError, subprocess.SubprocessError) as error:
        # Confidential subprocess exceptions can contain argv. No repr, cause,
        # traceback, credential-bearing error text or secret environment prints.
        print(safe_failure_message(error), file=sys.stderr)
        return 1
    if args.purpose == "publication":
        print(f"Publication-mode Developer ID proof complete for {result['architecture']}; publication still requires the same-run receipt gate.")
    else:
        print(f"Verification-only Developer ID proof complete for {result['architecture']}; release eligibility remains false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
