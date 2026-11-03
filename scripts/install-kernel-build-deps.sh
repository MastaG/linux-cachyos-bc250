#!/usr/bin/env bash
set -Eeuo pipefail

# Since CachyOS's "rust: Add support for rust and thinlto" (linux-cachyos
# 099f92d8c3, 2026-11-03) every LTO kernel PKGBUILD declares
# makedepends 'pahole>=1:1.32-2': that build has the --lang_exclude fix pahole
# needs to generate BTF for Rust modules from merged LTO units. Arch's own
# pahole may lag behind it (it was 1:1.32-1 then), and makepkg --syncdeps then
# stops with "target not found: pahole>=1:1.32-2".
#
# When Arch's version is too old, take pahole alone from the CachyOS repository
# through install-proton-build-deps.sh (version from the repository database,
# SHA256-checked). Once Arch catches up this does nothing and Arch's is used.

REQUIRED="1:1.32-2"
arch_version="$(pacman -Si pahole | awk '/^Version/ { print $3; exit }')"
[[ -n "$arch_version" ]] || {
    printf 'ERROR: cannot read the pahole version from the Arch repositories\n' >&2
    exit 1
}
if (( $(vercmp "$arch_version" "$REQUIRED") >= 0 )); then
    printf '==> pahole %s from Arch satisfies >=%s\n' "$arch_version" "$REQUIRED"
    exit 0
fi
printf '==> Arch has pahole %s, the kernels need >=%s: taking it from CachyOS\n' "$arch_version" "$REQUIRED"
"$(dirname -- "${BASH_SOURCE[0]}")/install-proton-build-deps.sh" pahole
installed="$(pacman -Q pahole | awk '{ print $2 }')"
(( $(vercmp "$installed" "$REQUIRED") >= 0 )) || {
    printf 'ERROR: installed pahole %s is still older than %s\n' "$installed" "$REQUIRED" >&2
    exit 1
}
