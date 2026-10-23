#!/usr/bin/env python3
"""Read and repair the sha256 a PKGBUILD declares for one of its sources.

This exists because upstream CachyOS commit c442588745 ("mesa: 26.2.5-2")
bumped mesa and mesa/lib32-mesa in one commit and wrote two DIFFERENT
sha256sums for the same file, "https://archive.mesa3d.org/mesa-$_pkgver.tar.xz"
(794b3d17... in mesa, dca42e0c... in lib32-mesa, and the tarball on the host is
794b3d17...).  Only one can be right, makepkg reports that as an opaque
"One or more files did not pass the validity check!" after a multi-minute
download, and nothing in this repository noticed before a build failed.

Three uses, sharing one parser so they cannot disagree:

  declared <PKGBUILD> <needle>            print the sum paired with the first
                                          source entry containing <needle>
  set      <PKGBUILD> <needle> <newsum>   rewrite that entry (needs a 64-hex
                                          newsum and that the old one is unique)
  check    <PKGBUILD> [<PKGBUILD>...]     exit 1 when the same source entry is
                                          declared with different sums

Source and checksum arrays are paired by index, so `source=()` plus
`source+=()` is read in order and matched against `sha256sums=()` plus
`sha256sums+=()` in the same order -- which is how makepkg pairs them, and how
scripts/prepare-mesa-pkgbuild.sh appends our patch set.

Entry text is normalised for one comparison: `$_pkgver` / `${_pkgver}` /
`$pkgver` / `${pkgver}` are expanded, with the same release-candidate rewrite
the PKGBUILDs do (`_pkgver=${pkgver/[a-z]/-&}`, a letter gets a dash before it),
so "mesa-$_pkgver.tar.xz" in a 26.2.5 PKGBUILD compares equal to a literal
"mesa-26.2.5.tar.xz".  Anything beyond that (two spellings of the same mirror,
different query strings) is NOT detected: this catches a wrong sum for an
identically written source, which is the mistake that actually happened.
"""

from __future__ import annotations

import html
import re
import shlex
import sys
from pathlib import Path

SHA256_LEN = 64
SUMS_ARRAY = "sha256sums"
SOURCE_ARRAY = "source"


class PkgbuildError(RuntimeError):
    """A PKGBUILD we cannot read confidently; never guess past this."""


def _first_array(text: str, name: str) -> list[str]:
    """The entries of the first plain `name=(...)`; `name+=(...)` is ignored.

    Appends are deliberately left out: mesa builds part of its own `source` in a
    top-level loop over `_crates`, so an appended entry does not sit at the index
    its appended sum does, and pairing them would compare a patch against a
    crate.  Only the initial arrays are safe to pair positionally.
    """
    match = re.search(rf"^{re.escape(name)}=\(", text, flags=re.M)
    if not match:
        raise PkgbuildError(f"{name}: no '{name}=(' array found")
    open_at = match.end() - 1
    depth = 0
    for pos in range(open_at, len(text)):
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
            if depth == 0:
                break
    else:
        raise PkgbuildError(f"{name}: array never closed")
    body = text[open_at + 1 : pos]
    # A trailing backslash-newline continues the entry, so join it first.
    body = re.sub(r"\\\r?\n", " ", body)
    return _tokenise(body, name)


def _tokenise(body: str, name: str) -> list[str]:
    try:
        return [tok for tok in shlex.split(body, comments=True) if tok]
    except ValueError as exc:  # unbalanced quote, stray backslash, ...
        raise PkgbuildError(f"{name}: cannot tokenise array: {exc}") from None


def pkgver_of(text: str) -> str:
    match = re.search(r"^pkgver=(\S+)$", text, flags=re.M)
    if not match:
        raise PkgbuildError("pkgver: no '^pkgver=' line")
    return match.group(1).strip("'\"")


def _expansions(text: str) -> dict[str, str]:
    pkgver = pkgver_of(text)
    # _pkgver=${pkgver/[a-z]/-&}: bash replaces only the FIRST match of the glob,
    # so 26.2.1rc1 -> 26.2.1-rc1 (not 26.2.1-r-c1). count=1 mirrors that; the
    # same rule is reproduced in scripts/fetch-mesa-tarball.sh with sed, which is
    # first-match-per-line by default.
    pkgver_dash = re.sub(r"[a-z]", lambda m: "-" + m.group(0), pkgver, count=1)
    return {
        "pkgver": pkgver,
        "_pkgver": pkgver_dash,
    }


def normalise(entry: str, expansions: dict[str, str]) -> str:
    out = entry
    for name, value in expansions.items():
        out = out.replace("${" + name + "}", value).replace("$" + name, value)
    return out.strip("'\"")


def source_sums(path: Path) -> list[tuple[str, str]]:
    """(normalised source entry, declared sha256) for the initial arrays only."""
    text = path.read_text(encoding="utf-8")
    expansions = _expansions(text)
    sources = _first_array(text, SOURCE_ARRAY)
    sums = _first_array(text, SUMS_ARRAY)
    if len(sources) > len(sums):
        raise PkgbuildError(
            f"{path.name}: {len(sources)} source entries but {len(sums)} "
            f"{SUMS_ARRAY} entries; makepkg pairs them by index"
        )
    bad = [
        (i, s)
        for i, s in enumerate(sums[: len(sources)])
        if len(s) != SHA256_LEN or not re.fullmatch(r"[0-9a-f]+", s, flags=re.I)
    ]
    if bad:
        i, s = bad[0]
        raise PkgbuildError(f"{path.name}: source #{i} has a non-sha256 sum {s!r}")
    return [(normalise(src, expansions), s) for src, s in zip(sources, sums)]


def mesa_published(html_text: str, filename: str) -> str:
    """The sha256 Mesa publishes for `filename` on its release-notes page.

    docs.mesa3d.org/relnotes/<version>.html carries a "SHA checksums" block, one
    line per file and digest, e.g.

        SHA256: 794b3d17...6138a0a5  mesa-26.2.5.tar.xz
        SHA512: 08c7d7ea...ccd6a     mesa-26.2.5.tar.xz

    The page is reStructuredText rendered to HTML, so the block is read out of
    the markup rather than trusted to stay in one place: every tag is dropped and
    the "SHA256: <64 hex> <filename>" line is searched for in the plain text.
    Raises if the file is not listed -- that is a reason to not override, never a
    reason to guess.
    """
    plain = html.unescape(re.sub(r"<[^>]+>", " ", html_text))
    for match in re.finditer(r"SHA256:\s*([0-9a-f]{64})\s+(\S+)", plain, flags=re.I):
        if match.group(2).strip() == filename:
            return match.group(1).lower()
    raise PkgbuildError(f"relnotes page lists no SHA256 for {filename!r}")


def declared(path: Path, needle: str) -> tuple[str, str]:
    """The (source, sum) pair whose source entry contains `needle`."""
    hits = [(src, s) for src, s in source_sums(path) if needle in src]
    if not hits:
        raise PkgbuildError(f"{path.name}: no source entry contains {needle!r}")
    if len(hits) > 1 and len({s for _, s in hits}) > 1:
        raise PkgbuildError(
            f"{path.name}: {needle!r} matches {len(hits)} entries with different sums"
        )
    return hits[0]


def set_declared(path: Path, needle: str, newsum: str) -> tuple[str, str]:
    """Point the entry's declared sum at `newsum`; returns (old, new)."""
    if not re.fullmatch(r"[0-9a-f]{64}", newsum):
        raise PkgbuildError(f"refusing to write a non-sha256 value {newsum!r}")
    text = path.read_text(encoding="utf-8")
    _, old = declared(path, needle)
    if text.count(old) != 1:
        raise PkgbuildError(
            f"{path.name}: declared sum {old} appears {text.count(old)} times, "
            "not the single place this tool expects to rewrite"
        )
    path.write_text(text.replace(old, newsum, 1), encoding="utf-8", newline="\n")
    return old, newsum


def clashes(paths: list[Path]) -> list[tuple[str, list[tuple[str, str]]]]:
    """(source, [(file, sum), ...]) for shared initial-array sources."""
    seen: dict[str, list[tuple[str, str]]] = {}
    for path in paths:
        for src, s in source_sums(path):
            seen.setdefault(src, []).append((path.name, s))
    return [
        (src, hits)
        for src, hits in seen.items()
        if len({s for _, s in hits}) > 1
    ]


def main(argv: list[str]) -> int:
    usage = (
        "usage: check-mesa-source-sums.py declared <PKGBUILD> <needle>\n"
        "       check-mesa-source-sums.py set <PKGBUILD> <needle> <newsum>\n"
        "       check-mesa-source-sums.py published <relnotes.html> <filename>\n"
        "       check-mesa-source-sums.py check <PKGBUILD> [<PKGBUILD>...]"
    )
    if len(argv) < 3:
        print(usage, file=sys.stderr)
        return 2
    cmd, args = argv[1], argv[2:]
    try:
        if cmd == "declared":
            if len(args) != 2:
                raise PkgbuildError("declared takes a PKGBUILD and a needle")
            src, s = declared(Path(args[0]), args[1])
            print(s)
            print(f"  entry: {src}", file=sys.stderr)
        elif cmd == "set":
            if len(args) != 3:
                raise PkgbuildError("set takes a PKGBUILD, a needle and a sum")
            old, new = set_declared(Path(args[0]), args[1], args[2])
            print(f"rewrote {old} -> {new}")
        elif cmd == "published":
            if len(args) != 2:
                raise PkgbuildError("published takes a relnotes HTML file and a filename")
            print(mesa_published(Path(args[0]).read_text(encoding="utf-8"), args[1]))
        elif cmd == "check":
            found = clashes([Path(a) for a in args])
            for src, hits in found:
                print(f"SAME SOURCE, DIFFERENT SUMS: {src}")
                for name, s in hits:
                    print(f"  {s}  {name}")
            if found:
                return 1
            print(f"ok: {len(args)} PKGBUILDs share no source with a conflicting sum")
        else:
            print(usage, file=sys.stderr)
            return 2
    except (PkgbuildError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
