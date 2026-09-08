#!/usr/bin/env python3
"""Choose an OptiScaler build whose OptiScaler.ini accepts every preset key.

The BC-250 FSR4 packages ship a fixed OptiScaler preset, applied through
protonfixes' PROTON_OPTISCALER_CONFIG. Our patched upscalers.py treats an
unknown key as fatal when a pinned manifest is in use -- it refuses the launch
rather than silently dropping the setting. That is the behaviour we want, but it
means an OptiScaler build that has renamed or removed an option turns into a
game that will not start.

So the choice is made here, at build time, instead of at a customer's launch:
track the latest nightly, but validate the preset against its shipped
OptiScaler.ini first and fall back to the mirrored known-good build when a key
is missing. The failure mode becomes "stays on a proven build", and the missing
keys are named in the build log so the preset can be updated deliberately.

Matching protonfixes' comparison exactly matters more than it looks. It uses a
bare configparser.ConfigParser(), which lowercases option names but leaves
section names alone, so the check has to be case-insensitive on options and
case-sensitive on sections. Anything hand-rolled drifts from what the launch
path actually enforces: the preset's "Plugins.LoadReShade" is spelled
"LoadReshade" in the ini and matches only because of that lowercasing.
"""

from __future__ import annotations

import argparse
import configparser
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# The known-good build. Every preset key is present in its OptiScaler.ini, and
# it is the build the upstream BC-250 FSR4 work was validated against.
FALLBACK_TAG = "nightly-20260904"
FALLBACK_ASSET = "OptiScaler_v10.0.0-pre1_20260904.7z"
FALLBACK_SHA256 = "730d5057338cf68adc3bf38a358985a04629ad00fae305bd717694a392216a53"

NIGHTLY_REPO = "optiscaler/OptiScaler-nightly"


def preset_keys(preset_path: Path) -> list[str]:
    preset = json.loads(preset_path.read_text())
    if isinstance(preset, dict) and "preset" in preset:
        preset = preset["preset"]
    return sorted(preset)


def missing_keys(ini_path: Path, keys: list[str]) -> list[str]:
    """Return preset keys the ini does not define, using protonfixes' semantics."""
    parser = configparser.ConfigParser(strict=False)
    # Deliberately NOT setting optionxform: the default lowercases option names,
    # which is what protonfixes does and what makes LoadReShade/LoadReshade match.
    parser.read(ini_path, encoding="utf-8-sig")

    missing = []
    for key in keys:
        section, _, option = key.partition(".")
        if not option or section not in parser or option not in parser[section]:
            missing.append(key)
    return missing


class NoExtractor(RuntimeError):
    """No 7z implementation is installed, so nothing can be verified."""


def extract_ini(archive: Path, workdir: Path) -> Path | None:
    """Extract OptiScaler.ini from the 7z. It sits at the archive root.

    Raises NoExtractor when no 7z tool exists at all: that is an environment
    problem, not evidence about the archive, and conflating the two produces a
    "this build is broken" warning when the truth is "install p7zip".
    """
    tried = False
    for tool in ("7z", "7za", "7zr"):
        try:
            subprocess.run(
                [tool, "x", "-y", f"-o{workdir}", str(archive), "OptiScaler.ini"],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError:
            tried = True
            continue
        tried = True
        found = workdir / "OptiScaler.ini"
        if found.is_file():
            return found
    if not tried:
        raise NoExtractor("no 7z, 7za or 7zr on PATH (install p7zip)")
    return None


def latest_nightly() -> tuple[str, str, str] | None:
    """Return (tag, asset name, download url) for the newest nightly, or None."""
    # Every nightly is flagged as a pre-release, and "gh release view" with no
    # tag resolves the latest *stable* release -- which this repo never
    # publishes, so it exits non-zero. Read the releases list directly instead;
    # element 0 is the newest regardless of the pre-release flag.
    try:
        out = subprocess.run(
            ["gh", "api", f"repos/{NIGHTLY_REPO}/releases?per_page=1",
             "--jq", ".[0] | {tag: .tag_name, assets: [.assets[] | "
                     "{name: .name, url: .browser_download_url}]}"],
            check=True, capture_output=True, text=True, timeout=120,
        ).stdout.strip()
    except Exception as exc:  # network, auth, rate limit -- all non-fatal
        print(f"::warning::could not query the latest OptiScaler nightly ({exc})", file=sys.stderr)
        return None
    if not out:
        return None
    data = json.loads(out)
    for asset in data.get("assets", []):
        if asset["name"].endswith(".7z"):
            return data["tag"], asset["name"], asset["url"]
    return None


def emit(tag: str, asset: str, sha256: str, mirrored: bool, out: Path | None) -> None:
    result = {"tag": tag, "asset": asset, "sha256": sha256, "mirrored": mirrored}
    text = "\n".join(f"OPTISCALER_{k.upper()}={v}" for k, v in result.items())
    print(text)
    if out:
        out.write_text(text + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", type=Path, required=True,
                    help="JSON file holding the OptiScaler preset (or {'preset': {...}})")
    ap.add_argument("--output", type=Path, help="write the selection as an env file")
    ap.add_argument("--force-fallback", action="store_true",
                    help="skip the nightly check and use the mirrored build")
    args = ap.parse_args()

    keys = preset_keys(args.preset)
    print(f"==> validating {len(keys)} OptiScaler preset keys", file=sys.stderr)

    if args.force_fallback:
        print("==> forced: using the mirrored known-good build", file=sys.stderr)
        emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
        return 0

    latest = latest_nightly()
    if latest is None:
        print(f"==> falling back to the mirrored {FALLBACK_TAG}", file=sys.stderr)
        emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
        return 0

    tag, asset, url = latest
    if tag == FALLBACK_TAG:
        print(f"==> latest nightly is the mirrored build ({tag})", file=sys.stderr)
        emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        archive = work / asset
        try:
            subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(archive), url],
                           check=True, timeout=900)
        except Exception as exc:
            print(f"::warning::could not download {tag} ({exc})", file=sys.stderr)
            print(f"==> falling back to the mirrored {FALLBACK_TAG}", file=sys.stderr)
            emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
            return 0

        try:
            ini = extract_ini(archive, work)
        except NoExtractor as exc:
            print(f"::warning::cannot validate the preset: {exc}", file=sys.stderr)
            print(f"==> falling back to the mirrored {FALLBACK_TAG}", file=sys.stderr)
            emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
            return 0
        if ini is None:
            print(f"::warning::{tag} has no OptiScaler.ini at the archive root", file=sys.stderr)
            print(f"==> falling back to the mirrored {FALLBACK_TAG}", file=sys.stderr)
            emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
            return 0

        gone = missing_keys(ini, keys)
        if gone:
            print(
                "::warning title=OptiScaler preset drift::"
                f"{tag} does not define {len(gone)} preset key(s): {', '.join(gone)}. "
                f"Using the mirrored {FALLBACK_TAG} instead; update the preset to move forward.",
                file=sys.stderr,
            )
            emit(FALLBACK_TAG, FALLBACK_ASSET, FALLBACK_SHA256, True, args.output)
            return 0

        sha = subprocess.run(["sha256sum", str(archive)], check=True,
                             capture_output=True, text=True).stdout.split()[0]
        print(f"==> {tag} accepts every preset key; using it", file=sys.stderr)
        emit(tag, asset, sha, False, args.output)
        return 0


if __name__ == "__main__":
    sys.exit(main())
