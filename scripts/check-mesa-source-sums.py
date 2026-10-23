#!/usr/bin/env python3
"""Read and repair the sha256 a PKGBUILD declares for one of its sources.

This exists because upstream CachyOS commit c442588745 ("mesa: 26.2.5-2")
bumped mesa and mesa/lib32-mesa in one commit and wrote two DIFFERENT
sha256sums for the same file, "https://archive.mesa3d.org/mesa-$_pkgver.tar.xz"
(794b3d17... in mesa, dca42e0c... in lib32-mesa, and the tarball on the host is
794b3d17...).  Only one can be right, makepkg reports that as an opaque
"One or more files did not pass the validity check!" after a multi-minute
download, and nothing in this repository noticed before a build failed.

Six uses, sharing one parser so they cannot disagree:

  declared <PKGBUILD> <needle>            print the sum paired with the first
                                          source entry containing <needle>
  set      <PKGBUILD> <needle> <newsum>   rewrite that entry (needs a 64-hex
                                          newsum and that the old one is unique)
  check    <PKGBUILD> [<PKGBUILD>...]     exit 1 when the same source entry is
                                          declared with different sums
  mismatch <PKGBUILD> <needle> <file>     print "MISMATCH <array> <index>
                                          <declared> <measured>" for EVERY checksum
                                          array the PKGBUILD declares for that entry
  sync     <PKGBUILD> <needle> <file>     rewrite every one of those entries from
                                          the file, printing "REPLACED <array>
                                          <index> <old> <new>" for each
  published <relnotes.html> <filename>    the digests Mesa publishes for a file

The multi-array case is not hypothetical: the same c442588745 commit also wrote a
wrong b2sums entry in lib32-mesa (347f1e11... where the file is cfcc4d72...), and
makepkg validates the b2sums array too -- the 2026-10-23 run fixed the sha256, got
past it, and then died in "Validating source files with b2sums".  Once the file is
confirmed by Mesa's relnotes, the file is the authority for every array.

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

import hashlib
import html
import re
import shlex
import sys
from pathlib import Path

SHA256_LEN = 64
SUMS_ARRAY = "sha256sums"
SOURCE_ARRAY = "source"

# Checksum arrays this tool can compute itself (makepkg's supported types, with
# the digest length each one expects in a PKGBUILD).  b2sums is 512-bit BLAKE2b,
# which is hashlib.blake2b's default digest size.  Anything else that shows up in
# a PKGBUILD is refused rather than guessed at.
SUPPORTED_ARRAYS = {
    "md5sums": ("md5", 32),
    "sha1sums": ("sha1", 40),
    "sha224sums": ("sha224", 56),
    "sha256sums": ("sha256", 64),
    "sha384sums": ("sha384", 96),
    "sha512sums": ("sha512", 128),
    "b2sums": ("blake2b", 128),
}


class PkgbuildError(RuntimeError):
    """A PKGBUILD we cannot read confidently; never guess past this."""


def _array_body_span(text: str, name: str, require: bool = True):
    """(start, end) of the body of the first plain `name=(...)`, or None."""
    match = re.search(rf"^{re.escape(name)}=\(", text, flags=re.M)
    if not match:
        if require:
            raise PkgbuildError(f"{name}: no '{name}=(' array found")
        return None
    open_at = match.end() - 1
    depth = 0
    for pos in range(open_at, len(text)):
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
            if depth == 0:
                return (open_at + 1, pos)
    raise PkgbuildError(f"{name}: array never closed")


def _first_array(text: str, name: str, require: bool = True) -> list[str]:
    """The entries of the first plain `name=(...)`; `name+=(...)` is ignored.

    Appends are deliberately left out: mesa builds part of its own `source` in a
    top-level loop over `_crates`, so an appended entry does not sit at the index
    its appended sum does, and pairing them would compare a patch against a
    crate.  Only the initial arrays are safe to pair positionally.
    """
    span = _array_body_span(text, name, require=require)
    if span is None:
        return []
    body = text[span[0] : span[1]]
    # A trailing backslash-newline continues the entry, so join it first.
    body = re.sub(r"\\\r?\n", " ", body)
    return _tokenise(body, name)


def _entries_with_offsets(text: str, name: str, require: bool = True) -> list[list[int | str]]:
    """[value, start, end] per entry, offsets absolute in `text`, quotes excluded.

    Values come from the same tokenizer as `_first_array`, and each one is located
    by searching forward from the previous match, so duplicated entries ("SKIP")
    still land on their own slot.  A quote-joining backslash shifts the offsets;
    refuse rather than write to the wrong place.
    """
    span = _array_body_span(text, name, require=require)
    if span is None:
        return []
    raw = text[span[0] : span[1]]
    if re.search(r"\\\r?\n", raw):
        raise PkgbuildError(f"{name}: a continued line; offsets would be wrong")
    out, pos = [], span[0]
    for value in _tokenise(raw, name):
        idx = raw.find(value, pos - span[0])
        if idx < 0:
            raise PkgbuildError(f"{name}: cannot locate entry {value!r} to rewrite it")
        out.append([value, span[0] + idx, span[0] + idx + len(value)])
        pos = span[0] + idx + len(value)
    return out


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


def published_checksums(html_text: str, filename: str) -> dict[str, str]:
    """Every digest Mesa publishes for `filename` on its release-notes page.

    The page lists SHA256 and SHA512 lines for the tarball (see the plain-text
    reading in `mesa_published`); both are returned, keyed as "sha256"/"sha512",
    so a caller can cross-check the file on two digests instead of one.
    """
    plain = html.unescape(re.sub(r"<[^>]+>", " ", html_text))
    found: dict[str, str] = {}
    for match in re.finditer(r"(SHA256|SHA512):\s*([0-9a-f]{64,128})\s+(\S+)", plain, flags=re.I):
        if match.group(3).strip() == filename:
            found[match.group(1).lower()] = match.group(2).lower()
    if not found:
        raise PkgbuildError(f"relnotes page lists no checksum for {filename!r}")
    return found


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
    found = published_checksums(html_text, filename)
    if "sha256" not in found:
        raise PkgbuildError(f"relnotes page lists no SHA256 for {filename!r}")
    return found["sha256"]


def declared(path: Path, needle: str) -> tuple[str, str]:
    """The (source, sum) pair whose source entry contains `needle` (sha256 only)."""
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


def file_digests(path: Path) -> dict[str, str]:
    """The digest of `path` for every array name in SUPPORTED_ARRAYS."""
    data = Path(path).read_bytes()
    return {
        name: hashlib.new(algo, data).hexdigest()
        for name, (algo, _hexlen) in SUPPORTED_ARRAYS.items()
    }


def source_index(text: str, needle: str) -> int:
    """The index of the source entry containing `needle` in the initial array."""
    expansions = _expansions(text)
    hits = [
        i
        for i, entry in enumerate(_entries_with_offsets(text, SOURCE_ARRAY))
        if needle in normalise(str(entry[0]), expansions)
    ]
    if not hits:
        raise PkgbuildError(f"no source entry contains {needle!r}")
    if len(hits) > 1:
        raise PkgbuildError(f"{needle!r} matches {len(hits)} source entries; refusing")
    return hits[0]


def mismatches(pkgbuild: Path, file: Path, needle: str) -> list[tuple[str, int, str, str]]:
    """(array, index, declared, measured) for every checksum array that disagrees.

    Only arrays that actually carry an entry for that source index are considered;
    an array with no entry there is makepkg's business, not ours.  An array this
    tool cannot compute (b3sums, sha3sums, ...) is an error: rewriting one array
    and leaving a wrong other one behind is how the 2026-10-23 run failed.
    """
    text = Path(pkgbuild).read_text(encoding="utf-8")
    index = source_index(text, needle)
    digests = file_digests(file)
    unknown = [
        name
        for name in re.findall(r"^(\w+sums)=\(", text, flags=re.M)
        if name not in SUPPORTED_ARRAYS
    ]
    if unknown:
        raise PkgbuildError(
            f"{pkgbuild.name}: cannot compute {' and '.join(sorted(unknown))}; "
            "refusing to rewrite only part of the sums"
        )
    out = []
    for name, (_algo, hexlen) in SUPPORTED_ARRAYS.items():
        entries = _entries_with_offsets(text, name, require=False)
        if not entries or index >= len(entries):
            continue
        declared = entries[index][0]
        if not re.fullmatch(r"[0-9a-f]+", declared, flags=re.I) or len(declared) != hexlen:
            raise PkgbuildError(
                f"{pkgbuild.name}: {name} entry #{index} is {declared!r}, not a "
                f"{hexlen}-hex digest; refusing to rewrite what it cannot read"
            )
        if declared.lower() != digests[name]:
            out.append((name, index, declared, digests[name]))
    return out


def sync_rewrite(pkgbuild: Path, file: Path, needle: str) -> list[tuple[str, int, str, str]]:
    """Point every checksum array of one source entry at the file itself."""
    text = Path(pkgbuild).read_text(encoding="utf-8")
    index = source_index(text, needle)
    digests = file_digests(file)
    changes = []
    for name, (_algo, _hexlen) in SUPPORTED_ARRAYS.items():
        entries = _entries_with_offsets(text, name, require=False)
        if not entries or index >= len(entries):
            continue
        declared, start, end = entries[index]
        if declared.lower() != digests[name]:
            changes.append((name, index, declared, digests[name], start, end))
    for name, _index, _old, _new, start, end in sorted(changes, key=lambda c: -c[4]):
        text = text[:start] + _new + text[end:]
    Path(pkgbuild).write_text(text, encoding="utf-8", newline="\n")
    return [(name, index, old, new) for name, index, old, new, _s, _e in changes]


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
        "       check-mesa-source-sums.py mismatch <PKGBUILD> <needle> <file>\n"
        "       check-mesa-source-sums.py sync <PKGBUILD> <needle> <file>\n"
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
            for algo, value in sorted(published_checksums(
                Path(args[0]).read_text(encoding="utf-8"), args[1]
            ).items()):
                print(f"{algo}={value}")
        elif cmd == "mismatch":
            if len(args) != 3:
                raise PkgbuildError("mismatch takes a PKGBUILD, a needle and the file")
            for name, index, want, got in mismatches(
                Path(args[0]), Path(args[2]), args[1]
            ):
                print(f"MISMATCH {name} {index} {want} {got}")
        elif cmd == "sync":
            if len(args) != 3:
                raise PkgbuildError("sync takes a PKGBUILD, a needle and the file")
            for name, index, old, new in sync_rewrite(
                Path(args[0]), Path(args[2]), args[1]
            ):
                print(f"REPLACED {name} {index} {old} {new}")
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
