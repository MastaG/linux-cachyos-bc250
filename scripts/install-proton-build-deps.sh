#!/usr/bin/env bash
set -Eeuo pipefail

# proton-cachyos-native declares two makedepends that do not exist in Arch's own
# repositories -- `afdko` and `mingw-w64-tools` are both AUR-only -- so
# `makepkg --syncdeps` fails with "target not found" in a vanilla Arch container:
#
#   error: target not found: afdko
#   error: target not found: mingw-w64-tools
#   ==> ERROR: 'pacman' failed to install missing dependencies.
#
# CachyOS builds that package in an environment that has their own repository,
# which carries both as ordinary prebuilt packages. Adding that repository here
# would also work, but this container builds the kernels and Mesa too, and a
# third-party repository in it could quietly supply different versions of
# ordinary build dependencies. So this installs just the packages that are
# actually missing, and nothing else changes.
#
# afdko needs one further package that is also AUR-only, python-ufonormalizer.
# Every other dependency it has is in Arch `extra`, so pacman resolves the rest
# normally -- verified by installing these three into a clean archlinux
# container and confirming makeotf, otf2otc, gendef, genidl and genpeimg.
#
# Versions are resolved from the repository database rather than pinned, so a
# CachyOS version bump does not turn into a 404 here, and each download is
# checked against the SHA256 that database states -- the same integrity check
# pacman itself would apply.

REPO="${CACHYOS_GENERIC_REPO:-https://mirror.cachyos.org/repo/x86_64/cachyos}"
PACKAGES=(afdko mingw-w64-tools python-ufonormalizer)

command -v bsdtar >/dev/null 2>&1 || {
    printf 'ERROR: bsdtar is required to read the package database\n' >&2
    exit 1
}

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

printf '==> Fetching the CachyOS package database\n'
curl -fsSL --retry 5 --retry-all-errors -o "$work/db.tar.zst" "${REPO}/cachyos.db.tar.zst"

# Each package's entry is "<name>-<pkgver>-<pkgrel>/desc"; find the one whose
# %NAME% is exactly what we asked for, so `afdko` cannot match `afdko-git`.
entry_for() {
    local wanted="$1" entry name
    while IFS= read -r entry; do
        name="$(bsdtar -xOf "$work/db.tar.zst" "${entry}desc" 2>/dev/null |
            awk '/^%NAME%$/ { getline; print; exit }')"
        if [[ "$name" == "$wanted" ]]; then
            printf '%s' "$entry"
            return 0
        fi
    done < <(bsdtar -tf "$work/db.tar.zst" 2>/dev/null | grep -E '/$')
    return 1
}

field_of() {
    bsdtar -xOf "$work/db.tar.zst" "${1}desc" 2>/dev/null |
        awk -v key="%${2}%" '$0 == key { getline; print; exit }'
}

downloaded=()
for package in "${PACKAGES[@]}"; do
    entry="$(entry_for "$package")" || {
        printf 'ERROR: %s is not in the CachyOS repository database\n' "$package" >&2
        exit 1
    }
    filename="$(field_of "$entry" FILENAME)"
    sha256="$(field_of "$entry" SHA256SUM)"
    [[ -n "$filename" && "$sha256" =~ ^[0-9a-f]{64}$ ]] || {
        printf 'ERROR: incomplete database entry for %s\n' "$package" >&2
        exit 1
    }

    curl -fsSL --retry 5 --retry-all-errors -o "$work/$filename" "${REPO}/${filename}"
    actual="$(sha256sum "$work/$filename" | awk '{print $1}')"
    [[ "$actual" == "$sha256" ]] || {
        printf 'ERROR: %s does not match the SHA256 its repository states\n' "$filename" >&2
        printf '       expected %s\n       got      %s\n' "$sha256" "$actual" >&2
        exit 1
    }
    printf '    %s (sha256 verified)\n' "$filename"
    downloaded+=("$work/$filename")
done

# One transaction, so pacman resolves afdko against python-ufonormalizer here
# and everything else from Arch.
pacman -U --noconfirm "${downloaded[@]}"

missing=()
for binary in makeotf otf2otc gendef genidl genpeimg; do
    command -v "$binary" >/dev/null 2>&1 || missing+=("$binary")
done
(( ${#missing[@]} == 0 )) || {
    printf 'ERROR: installed, but these tools are still not on PATH: %s\n' "${missing[*]}" >&2
    exit 1
}

printf '==> Proton build dependencies installed (%s)\n' "${PACKAGES[*]}"
