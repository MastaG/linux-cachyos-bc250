#!/usr/bin/env bash
# Packages this repository used to build and no longer does.
#
# out/repo is seeded from the previous release on every run and the database is
# rebuilt from whatever *.pkg.tar.zst is there, so deleting a PKGBUILD on its own
# leaves the last build published forever -- nothing else ever revisits it.
# Worse than clutter: aic8800d80-dkms was published at pkgrel 7, above the AUR
# package's 6, so left in place it would shadow the AUR package (correct since
# upstream merged our fix on 2026-09-24) for everyone with this repository
# enabled.
#
# This file is deliberately NOT scripts/repo-package-helpers.sh: that file is
# hashed into every component's source fingerprint, so an entry here would
# rebuild three kernels, three Mesas and three Protons for a one-package
# retirement. Only the linux-cachyos-bc250-meta fingerprint hashes this file --
# a metapackage that builds in seconds -- which is enough to make the run reach
# the database builders where retire_packages runs (nothing runs when no
# fingerprint changed).
#
# retire_packages runs in both database builders (update-repo-db.sh, which every
# intermediate and final database goes through, and finalize-repository.sh
# before its own package enumeration), after the publish-state snapshot the
# workflow takes right after seeding. That order is what lets
# publish-repo-delta.sh delete the release assets, not just the database entry.
# One transient: on the rare restore-from-workflow-artifact path the seed step
# republishes the artifact wholesale before the first retire pass, and the next
# delta publish removes the retired files again.
#
# Scope: single-package components that publish <pkgbase>-info.env, -PKGBUILD
# and .SRCINFO. A kernel (split package, extra -config asset) would need more.
#
# Keep an entry for at least the workflow-artifact retention window (14 days)
# after the release stops carrying the assets: a restore from an older artifact
# would otherwise bring the package back with nothing left to remove it.
RETIRED_PACKAGES=(
    aic8800d80-dkms
)

# Needs remove_pkgbase_from_repo from repo-package-helpers.sh; callers source
# that first.
retire_packages() {
    local out_dir="$1" root pkgbase sidecar
    root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

    for pkgbase in "${RETIRED_PACKAGES[@]}"; do
        # A package that is both built and retired would have every fresh
        # build deleted right after it is staged, and the log would read like
        # a routine replacement. Refuse loudly instead.
        if [[ -d "$root/packages/$pkgbase" ]]; then
            printf 'ERROR: %s is listed in RETIRED_PACKAGES but packages/%s still exists\n' \
                "$pkgbase" "$pkgbase" >&2
            return 1
        fi
        printf '==> Retiring %s\n' "$pkgbase"
        remove_pkgbase_from_repo "$out_dir" "$pkgbase"
        for sidecar in "$pkgbase-info.env" "$pkgbase-PKGBUILD" "$pkgbase.SRCINFO"; do
            if [[ -e "$out_dir/$sidecar" ]]; then
                printf '==> Removing retired asset: %s\n' "$sidecar"
                rm -f -- "$out_dir/$sidecar"
            fi
        done
    done
}
