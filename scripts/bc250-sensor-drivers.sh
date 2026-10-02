# shellcheck shell=bash
# Shared description of the two BC-250 hwmon driver sources, sourced by
# prepare-pkgbuild.sh and source-fingerprint.sh so both always fetch the same
# files from the same pinned commits.
#
# Usage:
#   source scripts/bc250-sensor-drivers.sh
#   bc250_sensor_drivers_resolve            # fills BC250_VRM_COMMIT/BC250_MEMORY_COMMIT if unset
#   bc250_sensor_drivers_fetch <dest-dir>   # downloads every source file into <dest-dir>

BC250_SENSOR_VRM_FILES=(bc250_vrm.c)
BC250_SENSOR_MEMORY_FILES=(bc250_memory.c bc250_smu.c bc250_smu.h bc250_smu_patch.c)

bc250_sensor_drivers_resolve() {
    local root="${ROOT_DIR:?ROOT_DIR must be set}" line
    if [[ -z "${BC250_VRM_COMMIT:-}" || -z "${BC250_MEMORY_COMMIT:-}" ]]; then
        while IFS= read -r line; do
            case "$line" in
                BC250_VRM_COMMIT=*) [[ -n "${BC250_VRM_COMMIT:-}" ]] || BC250_VRM_COMMIT="${line#*=}" ;;
                BC250_MEMORY_COMMIT=*) [[ -n "${BC250_MEMORY_COMMIT:-}" ]] || BC250_MEMORY_COMMIT="${line#*=}" ;;
            esac
        done < <("$root/scripts/resolve-bc250-sensor-drivers.sh")
    fi
    [[ "$BC250_VRM_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
        printf 'ERROR: invalid BC250_VRM_COMMIT: %s\n' "$BC250_VRM_COMMIT" >&2
        return 1
    }
    [[ "$BC250_MEMORY_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
        printf 'ERROR: invalid BC250_MEMORY_COMMIT: %s\n' "$BC250_MEMORY_COMMIT" >&2
        return 1
    }
    BC250_VRM_SOURCE_URL="https://raw.githubusercontent.com/Hexxeh/bc250-vrm-dkms/${BC250_VRM_COMMIT}"
    BC250_MEMORY_SOURCE_URL="https://raw.githubusercontent.com/Hexxeh/bc250-memory-dkms/${BC250_MEMORY_COMMIT}"
}

bc250_sensor_drivers_fetch() {
    local dest="$1" file
    for file in "${BC250_SENSOR_VRM_FILES[@]}"; do
        curl -fsSL --retry 5 --retry-all-errors -o "$dest/$file" "$BC250_VRM_SOURCE_URL/$file"
    done
    for file in "${BC250_SENSOR_MEMORY_FILES[@]}"; do
        curl -fsSL --retry 5 --retry-all-errors -o "$dest/$file" "$BC250_MEMORY_SOURCE_URL/$file"
    done
}

# Every file name, in a fixed order (PKGBUILD source=() and the install step).
bc250_sensor_driver_files() {
    printf '%s\n' "${BC250_SENSOR_VRM_FILES[@]}" "${BC250_SENSOR_MEMORY_FILES[@]}"
}
