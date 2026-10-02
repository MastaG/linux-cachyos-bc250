#!/usr/bin/env bash
# Shared helpers for package builders that stage packages into out/repo.

# Remove a package base's files from out/repo before a fresh build is staged.
#
# By default the files are recorded in out/repo/archive-index.txt first: they
# stay on the release as downloadable older builds (scripts/package-archive.py
# keeps the newest three per package base) but leave out/repo, so neither the
# database nor the workflow artifact carries them. Pass "delete" as the third
# argument to drop them for good (a retired package).
remove_pkgbase_from_repo() {
    local out_dir="$1"
    local wanted_pkgbase="$2"
    local mode="${3:-archive}"
    local package existing_pkgbase pkginfo version root

    root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    shopt -s nullglob
    for package in "$out_dir"/*.pkg.tar.zst; do
        pkginfo="$(bsdtar -xOf "$package" .PKGINFO 2>/dev/null)"
        existing_pkgbase="$(awk -F ' = ' '$1 == "pkgbase" { print $2; exit }' <<<"$pkginfo")"
        if [[ "$existing_pkgbase" == "$wanted_pkgbase" ]]; then
            if [[ "$mode" == archive ]]; then
                version="$(awk -F ' = ' '$1 == "pkgver" { print $2; exit }' <<<"$pkginfo")"
                python3 "$root/scripts/package-archive.py" add "$out_dir" \
                    "$(basename -- "$package")" "$wanted_pkgbase" "$version"
                printf '==> Archiving previous %s package: %s\n' \
                    "$wanted_pkgbase" "$(basename -- "$package")"
            else
                printf '==> Removing previous %s package: %s\n' \
                    "$wanted_pkgbase" "$(basename -- "$package")"
            fi
            rm -f -- "$package"
        fi
    done
}

prune_stale_patches() {
    # out/repo is seeded from the previous release, and the per-component
    # builders only ever add this run's current patch files -- a rename or
    # renumbering otherwise leaves the old filename published forever, since
    # nothing else ever revisits it. This removes any published patch under
    # $prefix that the current $patch_dir no longer has.
    #
    # Anchored on a 4-digit patch number rather than a bare "$prefix*.patch"
    # glob: patches/linux-cachyos and patches/linux-cachyos-rc share a
    # "linux-cachyos-" prefix relationship, and a loose glob run for the
    # stable set would also match (and wrongly delete) the RC set's assets.
    local out_dir="$1" patch_dir="$2" prefix="$3"
    local asset base name

    shopt -s nullglob
    for asset in "$out_dir/$prefix"[0-9][0-9][0-9][0-9]-*.patch; do
        base="$(basename -- "$asset")"
        name="${base#"$prefix"}"
        if [[ ! -f "$patch_dir/$name" ]]; then
            printf '==> Removing stale patch asset: %s\n' "$base"
            rm -f -- "$asset"
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
