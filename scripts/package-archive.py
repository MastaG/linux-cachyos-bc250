#!/usr/bin/env python3
"""Keep the previous builds of every package on the release, outside the database.

The pacman database only ever lists the current build of each package, but the
repository also keeps the three previous builds per package base as release
assets, so a user can downgrade with `pacman -U <url>` without relying on a
local package cache (which bc250-paccache-cleanup empties).

State lives in out/repo/archive-index.txt, itself a release asset, one line per
file:

    <file>\t<pkgbase>\t<version>\t<archived-at>\t<status>

status "archived": the file stays on the release; seeding skips it, so it never
    returns to out/repo, the database or the workflow artifact.
status "pruned": pushed out of the retention window (or its package retired);
    publish-repo-delta.sh deletes it from the release. Pruned lines are kept
    for a few days so a failed deletion is retried, then dropped.

Commands:
    add <out_dir> <file> <pkgbase> <version>   record a file a build is replacing
    retire <out_dir> <pkgbase>                 prune every archived build of pkgbase
    maintain <out_dir> [keep]                  apply retention (default keep=3)
"""
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key
from pathlib import Path
import subprocess
import sys

INDEX = "archive-index.txt"
HEADER = "# file\tpkgbase\tversion\tarchived-at\tstatus\n"
PRUNED_GRACE = timedelta(days=7)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(out_dir: Path) -> list[list[str]]:
    path = out_dir / INDEX
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 5:
            raise SystemExit(f"ERROR: malformed {INDEX} line: {line!r}")
        rows.append(fields)
    return rows


def save(out_dir: Path, rows: list[list[str]]) -> None:
    text = HEADER + "".join("\t".join(r) + "\n" for r in rows)
    (out_dir / INDEX).write_text(text, encoding="utf-8")


def vercmp(a: str, b: str) -> int:
    return int(subprocess.run(["vercmp", a, b], capture_output=True, text=True, check=True).stdout)


def add(out_dir: Path, file: str, pkgbase: str, version: str) -> None:
    rows = [r for r in load(out_dir) if r[0] != file]
    rows.append([file, pkgbase, version, now(), "archived"])
    save(out_dir, rows)


def retire(out_dir: Path, pkgbase: str) -> None:
    rows = load(out_dir)
    for r in rows:
        if r[1] == pkgbase and r[4] == "archived":
            r[4] = "pruned"
            r[3] = now()
    save(out_dir, rows)


def maintain(out_dir: Path, keep: int) -> None:
    current = {p.name for p in out_dir.glob("*.pkg.tar.zst")}
    rows = []
    for r in load(out_dir):
        # A file that is current again (a rebuild with an unchanged version)
        # must never be archived or pruned: pruning would delete the live asset.
        if r[0] in current:
            continue
        rows.append(r)

    # Retention: per pkgbase, keep the files of the `keep` newest archived versions.
    versions: dict[str, set[str]] = {}
    for r in rows:
        if r[4] == "archived":
            versions.setdefault(r[1], set()).add(r[2])
    kept: dict[str, set[str]] = {}
    for pkgbase, vs in versions.items():
        newest = sorted(vs, key=cmp_to_key(vercmp), reverse=True)[:keep]
        kept[pkgbase] = set(newest)
    stamp = now()
    for r in rows:
        if r[4] == "archived" and r[2] not in kept[r[1]]:
            r[4] = "pruned"
            r[3] = stamp

    # Forget pruned files once their deletion has had a week of retries.
    cutoff = datetime.now(timezone.utc) - PRUNED_GRACE
    rows = [r for r in rows
            if not (r[4] == "pruned"
                    and datetime.strptime(r[3], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) < cutoff)]
    rows.sort(key=lambda r: (r[1], r[0]))
    save(out_dir, rows)
    archived = sum(r[4] == "archived" for r in rows)
    pruned = sum(r[4] == "pruned" for r in rows)
    print(f"==> package archive: {archived} archived file(s) kept, {pruned} pruned file(s) pending deletion")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        raise SystemExit(__doc__)
    cmd, out_dir = argv[1], Path(argv[2])
    if cmd == "add" and len(argv) == 6:
        add(out_dir, argv[3], argv[4], argv[5])
    elif cmd == "retire" and len(argv) == 4:
        retire(out_dir, argv[3])
    elif cmd == "maintain" and len(argv) in (3, 4):
        maintain(out_dir, int(argv[3]) if len(argv) == 4 else 3)
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
