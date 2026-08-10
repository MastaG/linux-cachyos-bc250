#!/usr/bin/env bash
# Shared helpers for package builders that stage packages into out/repo.

remove_pkgbase_from_repo() {
    local out_dir="$1"
    local wanted_pkgbase="$2"
    local package existing_pkgbase

    shopt -s nullglob
    for package in "$out_dir"/*.pkg.tar.zst; do
        existing_pkgbase="$(
            bsdtar -xOf "$package" .PKGINFO 2>/dev/null |
                awk -F ' = ' '$1 == "pkgbase" { print $2; exit }'
        )"
        if [[ "$existing_pkgbase" == "$wanted_pkgbase" ]]; then
            printf '==> Removing previous %s package: %s\n' \
                "$wanted_pkgbase" "$(basename -- "$package")"
            rm -f -- "$package"
        fi
    done
}

normalize_repo_package_filenames() {
    local out_dir="$1"
    local package pkginfo package_name package_version package_arch
    local filename_version target

    shopt -s nullglob
    for package in "$out_dir"/*.pkg.tar.zst; do
        [[ "$(basename -- "$package")" == *:* ]] || continue

        pkginfo="$(bsdtar -xOf "$package" .PKGINFO)"
        package_name="$(awk -F ' = ' '$1 == "pkgname" { print $2; exit }' <<<"$pkginfo")"
        package_version="$(awk -F ' = ' '$1 == "pkgver" { print $2; exit }' <<<"$pkginfo")"
        package_arch="$(awk -F ' = ' '$1 == "arch" { print $2; exit }' <<<"$pkginfo")"

        if [[ -z "$package_name" || -z "$package_version" || -z "$package_arch" ]]; then
            printf 'ERROR: could not read package metadata from %s\n' "$package" >&2
            return 1
        fi

        filename_version="${package_version#*:}"
        target="$out_dir/${package_name}-${filename_version}-${package_arch}.pkg.tar.zst"

        if [[ -e "$target" && "$target" != "$package" ]]; then
            printf 'ERROR: normalized package filename already exists: %s\n' "$target" >&2
            return 1
        fi

        printf '==> Normalizing package filename: %s -> %s\n' \
            "$(basename -- "$package")" "$(basename -- "$target")"
        mv -- "$package" "$target"
    done
}
