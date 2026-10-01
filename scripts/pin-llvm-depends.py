#!/usr/bin/env python3
"""Pin every LLVM-linked package in a Mesa PKGBUILD to the LLVM it was built with.

Upstream's Mesa packages depend on plain ``llvm-libs``, which is fine for Arch and
CachyOS: they rebuild Mesa in the same push as a new LLVM. This repository
builds Mesa separately, so a user's ``pacman -Syu`` can pull in a new LLVM while
our Mesa still needs the old ``libLLVM.so.<major>.<minor>``. When that happened
(LLVM 23, 2026-10-01) no Vulkan or OpenGL driver could load and the BC-250 came
up without gamescope or a desktop.

With the pin, pacman refuses that combination with a dependency error instead,
until a Mesa built against the new LLVM is published:

- 64-bit packages get ``libLLVM.so=<major>.<minor>-64``, the soname that
  ``llvm-libs`` itself provides.
- 32-bit packages get ``lib32-llvm-libs>=[epoch:]<major>.<minor>`` and
  ``<[epoch:]<major>.<minor+1>``, because ``lib32-llvm-libs`` provides no soname.

Point releases and rebuilds of the same LLVM <major>.<minor> keep the soname and
still install. The versions are read inside each package function, in the
build container, from the LLVM that was actually installed for the build.

Usage: pin-llvm-depends.py <PKGBUILD>
"""
from pathlib import Path
import re
import sys

HELPER = r'''
# BC-250: pin to the LLVM this package was built with (scripts/pin-llvm-depends.py).
_bc250_pin_llvm() {
  local dep version epoch major minor rest
  for dep in "${depends[@]}"; do
    case "$dep" in
      lib32-llvm-libs*)
        version="$(LC_ALL=C pacman -Q lib32-llvm-libs 2>/dev/null | awk '{print $2}')"
        [[ -n "$version" ]] || { echo "==> ERROR: lib32-llvm-libs is not installed; cannot pin" >&2; return 1; }
        epoch=""
        if [[ "$version" == *:* ]]; then epoch="${version%%:*}:"; version="${version#*:}"; fi
        version="${version%%-*}"; major="${version%%.*}"; rest="${version#*.}"; minor="${rest%%.*}"
        depends+=("lib32-llvm-libs>=${epoch}${major}.${minor}" "lib32-llvm-libs<${epoch}${major}.$((minor + 1))")
        return 0
        ;;
      llvm-libs*)
        dep="$(LC_ALL=C pacman -Qi llvm-libs 2>/dev/null | grep -oE 'libLLVM\.so=[^ ]+' | head -n 1)"
        [[ -n "$dep" ]] || { echo "==> ERROR: llvm-libs provides no libLLVM.so soname; cannot pin" >&2; return 1; }
        depends+=("$dep")
        return 0
        ;;
    esac
  done
}
'''

# A package function's depends array: "  depends=(" ... ")" (multi-line, as in the
# stable/lib32 PKGBUILDs) or "  depends=('a' 'b' $_llvm ...)" (as in mesa-git).
DEPENDS = re.compile(r'(\n(package_[A-Za-z0-9_.+-]+)\(\) \{\n(?:[^\n]*\n)*?  depends=\([^)]*\)\n)')


def is_llvm_linked(block: str) -> bool:
    deps = block[block.index('depends=('):]
    return bool(re.search(r'(^|[\s\'"(])(lib32-)?llvm-libs\b|\$\{?_(lib32_)?llvm\b', deps))


def main() -> int:
    path = Path(sys.argv[1])
    text = path.read_text(encoding='utf-8')
    if '_bc250_pin_llvm' in text:
        raise SystemExit(f'ERROR: {path} already pins LLVM')

    pinned = []

    def add_call(match: re.Match) -> str:
        block = match.group(1)
        if not is_llvm_linked(block):
            return block
        pinned.append(match.group(2))
        return block + '  _bc250_pin_llvm\n'

    text = DEPENDS.sub(add_call, text)
    if not pinned:
        raise SystemExit(f'ERROR: no LLVM-linked package function found in {path}; review the PKGBUILD')
    path.write_text(text.rstrip('\n') + '\n' + HELPER, encoding='utf-8', newline='\n')
    print(f'==> Pinned LLVM for: {", ".join(pinned)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
