#!/usr/bin/env bash
set -Eeuo pipefail

# usage: install-kernel-build-deps.sh <PKGBUILD>     (as root, before makepkg --syncdeps)
#
# Since CachyOS's "rust: Add support for rust and thinlto" (linux-cachyos
# 099f92d8c3, 2026-11-03) their LTO kernel PKGBUILDs declare a minimum pahole,
# 'pahole>=1:1.32-2' then: that build has the --lang_exclude fix pahole needs to
# generate BTF for Rust modules from merged LTO units. Arch's own pahole can lag
# behind (1:1.32-1 then), and makepkg --syncdeps stops with
# "target not found: pahole>=...".
#
# The minimum is read from the PKGBUILD being built, so a later bump upstream is
# followed without a change here. Only when Arch's pahole is older than that is
# pahole alone taken from the CachyOS repository through
# install-proton-build-deps.sh (version from the repository database,
# SHA256-checked). When the PKGBUILD no longer asks for a version, or Arch
# already has it, this does nothing and says the workaround can go.

pkgbuild="${1:?usage: $0 <PKGBUILD>}"
[[ -r "$pkgbuild" ]] || { printf 'ERROR: cannot read %s\n' "$pkgbuild" >&2; exit 1; }

required=""
while IFS= read -r version; do
    if [[ -z "$required" ]] || (( $(vercmp "$version" "$required") > 0 )); then
        required="$version"
    fi
done < <(grep -oE "pahole>=[0-9][0-9A-Za-z:._+-]*" "$pkgbuild" | sed 's/^pahole>=//' | sort -u)

if [[ -z "$required" ]]; then
    printf '==> pahole: the PKGBUILD asks for no minimum version; the CachyOS fetch (install-kernel-build-deps.sh) is no longer needed, remove it\n'
    exit 0
fi

arch_version="$(pacman -Si pahole | awk '/^Version/ { print $3; exit }')"
[[ -n "$arch_version" ]] || {
    printf 'ERROR: cannot read the pahole version from the Arch repositories\n' >&2
    exit 1
}
if (( $(vercmp "$arch_version" "$required") >= 0 )); then
    printf '==> pahole: Arch has %s, the PKGBUILD needs >=%s; the CachyOS fetch (install-kernel-build-deps.sh) is no longer needed, remove it\n' \
        "$arch_version" "$required"
    exit 0
fi

installed=""
if pacman -Q pahole >/dev/null 2>&1; then    # not installed in a fresh container
    installed="$(pacman -Q pahole | awk '{ print $2 }')"
fi
if [[ -n "$installed" ]] && (( $(vercmp "$installed" "$required") >= 0 )); then
    printf '==> pahole %s already installed (>=%s)\n' "$installed" "$required"
    exit 0
fi

printf '==> pahole: Arch has %s, the PKGBUILD needs >=%s: taking it from CachyOS\n' "$arch_version" "$required"
"$(dirname -- "${BASH_SOURCE[0]}")/install-proton-build-deps.sh" pahole
installed="$(pacman -Q pahole | awk '{ print $2 }')"
(( $(vercmp "$installed" "$required") >= 0 )) || {
    printf 'ERROR: CachyOS has pahole %s, still older than the >=%s the PKGBUILD needs\n' "$installed" "$required" >&2
    exit 1
}
