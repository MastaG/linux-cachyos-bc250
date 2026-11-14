#!/usr/bin/env bash
# ROCm + PyTorch wheels for the BC-250 (gfx1013), built with TheRock in its own
# manylinux image. Inputs are pinned in rocm/pins.env and rocm/patches/.
#
#   rocm/build-rocm.sh [stage...]       default: all
#     sources     check out TheRock + PyTorch at the pins, apply our patches
#     rocm        build ROCm (artifacts + dist)
#     wheels      ROCm Python wheels from those artifacts
#     torch       torch, torchvision, torchaudio against the ROCm wheels
#     wheelhouse  every wheel the bc250-pytorch package installs, PyPI deps included
#     all         the five above, in order
#     build-id    print the id of this set of inputs (names the release assets)
#     shell       a shell in the build container
#
# State lives in $BC250_ROCM_WORK (default ~/.cache/bc250-rocm): ~31 GB of
# sources, the build tree and ccache, ~150 GB in all. Keep it between runs: a
# rebuild after a small change takes minutes, a cold one most of a night.
# Limits: BC250_BUILD_MEMORY (20g, also caps swap) and BC250_BUILD_CPUS (8).
# With more CPUs the 20g cap is too small for Flang and MIOpen's tests.
set -Eeuo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=pins.env
set -a; source "$HERE/pins.env"; set +a
WORK="${BC250_ROCM_WORK:-$HOME/.cache/bc250-rocm}"
SRC="$WORK/TheRock"
OUT="$WORK/out"
MEMORY="${BC250_BUILD_MEMORY:-20g}"
CPUS="${BC250_BUILD_CPUS:-8}"
CLI="${CONTAINER_CLI:-podman}"
PY="/opt/python/$PYTHON_TAG/bin/python"
TORCH_DIR=/therock/src/external-builds/pytorch

build_id() {
    # Everything that decides what gets built, so equal ids mean equal inputs.
    (cd "$HERE" && sha256sum pins.env build-rocm.sh patches/*/*.patch) | sha256sum | cut -c1-12
}

run() {
    local name="$1" script="$2"
    mkdir -p "$OUT" "$SRC"
    "$CLI" run --rm ${TTY:-} --name "bc250-rocm-$name" \
        --memory "$MEMORY" --memory-swap "$MEMORY" --cpus "$CPUS" --security-opt label=disable \
        --mount "type=bind,src=$OUT,dst=/therock/output" \
        --mount "type=bind,src=$SRC,dst=/therock/src" \
        --mount "type=bind,src=$HERE,dst=/bc250,ro" \
        -e CCACHE_DIR=/therock/output/caches/ccache -e CCACHE_MAXSIZE=80G \
        -e PIP_CACHE_DIR=/therock/output/caches/pip \
        -e THEROCK_COMMIT -e PYTORCH_REPO -e PYTORCH_COMMIT -e PYTHON_TAG \
        -e THEROCK_REPO -e BUILD_ID="$(build_id)" \
        "$BUILD_IMAGE" taskset -c "0-$((CPUS - 1))" bash -c "set -Eeuo pipefail; PY=$PY; $script"
}

stage_sources() {
    if [[ "$(cat "$OUT/sources.stamp" 2>/dev/null)" == "$(build_id)" ]]; then
        echo "==> sources: unchanged since the last checkout ($(build_id))"
        return
    fi
    run sources '
git config --global --add safe.directory "*"
cd /therock/src
[[ -d .git ]] || git clone -q "$THEROCK_REPO" .
git fetch -q origin "$THEROCK_COMMIT"
# Undo our patches from a previous checkout before moving to the pins.
git -C rocm-libraries checkout -q -f HEAD -- . 2>/dev/null || true
git checkout -q -f --detach "$THEROCK_COMMIT"
$PY -m pip install -q -r requirements.txt
$PY build_tools/fetch_sources.py --jobs 8 \
  --no-include-media-libs --no-include-debug-tools --no-include-ml-frameworks
for p in /bc250/patches/therock/*.patch; do git apply "$p"; done
for p in /bc250/patches/rocm-libraries/*.patch; do git -C rocm-libraries apply "$p"; done

cd '"$TORCH_DIR"'
if [[ "$(git -C pytorch rev-parse -q --verify THEROCK_UPSTREAM_DIFFBASE 2>/dev/null)" != "$PYTORCH_COMMIT" ]]; then
  rm -rf pytorch pytorch_vision pytorch_audio
  $PY pytorch_torch_repo.py checkout --gitrepo-origin "$PYTORCH_REPO" --repo-hashtag "$PYTORCH_COMMIT" --no-commit-hipify
  $PY pytorch_audio_repo.py checkout --require-related-commit --no-commit-hipify
  $PY pytorch_vision_repo.py checkout --require-related-commit --no-commit-hipify
fi
for d in pytorch pytorch_vision pytorch_audio; do
  echo "$d: $(git -C $d log -1 --format="%h %s" THEROCK_UPSTREAM_DIFFBASE)"
done
'
    build_id > "$OUT/sources.stamp"
}

stage_rocm() {
    run rocm '
export PATH=$(dirname $PY):$PATH
pip install -q -r /therock/src/requirements.txt
cmake -GNinja -S /therock/src -B /therock/output/build \
  -DTHEROCK_AMDGPU_FAMILIES=gfx1013-bc250 \
  -DTHEROCK_ENABLE_ALL=OFF \
  -DTHEROCK_ENABLE_BLAS=ON -DTHEROCK_ENABLE_RAND=ON -DTHEROCK_ENABLE_FFT=ON \
  -DTHEROCK_ENABLE_PRIM=ON -DTHEROCK_ENABLE_SPARSE=ON -DTHEROCK_ENABLE_SOLVER=ON \
  -DTHEROCK_ENABLE_MIOPEN=ON \
  -DTHEROCK_ENABLE_LIBHIPCXX=ON \
  -DTHEROCK_BUNDLE_SYSDEPS=ON -DFLANG_PARALLEL_COMPILE_JOBS=1 \
  -DTHEROCK_DIST_PYTHON_EXECUTABLES=$PY \
  -DTHEROCK_SHARED_PYTHON_EXECUTABLES=/opt/python-shared/$PYTHON_TAG/bin/python3 \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache
time cmake --build /therock/output/build --target therock-artifacts therock-dist
'
}
# LIBHIPCXX: torch 2.13 takes the CCCL 3 code path with hipCUB 3.x and needs
# libhipcxx for ::cuda::maximum. FLANG jobs 1: two Flang compiles exceed 20g.

stage_wheels() {
    run wheels '
export PATH=$(dirname $PY):$PATH
pip install -q -r /therock/src/requirements.txt
rm -rf /therock/output/packages
python /therock/src/build_tools/build_python_packages.py \
  --artifact-dir /therock/output/build/artifacts --dest-dir /therock/output/packages
'
}

stage_torch() {
    run torch '
VENV=/therock/output/torch-venv
[[ -x $VENV/bin/python ]] || $PY -m venv $VENV
. $VENV/bin/activate
pip install -q -r '"$TORCH_DIR"'/requirements-ci.txt
# One GPU: no RCCL in this ROCm build. NNPACK still uses cmake_minimum_required < 3.5.
export USE_NCCL=0 USE_RCCL=0 CMAKE_POLICY_VERSION_MINIMUM=3.5
# Libraries this narrow ROCm build does not ship; torch does not link them.
export THEROCK_PYTORCH_SKIP_PRELOADS=hipdnn,rccl,hipfile
export MAX_JOBS=$(nproc)
# Build options only seed a fresh CMake cache; never reuse one across runs.
rm -f '"$TORCH_DIR"'/pytorch/build/CMakeCache.txt
rm -rf /therock/output/torch-wheels
cd '"$TORCH_DIR"'
time python build_prod_wheels.py build \
  --install-rocm --find-links /therock/output/packages/dist --index-url https://pypi.org/simple \
  --rocm-extras device \
  --pytorch-rocm-arch gfx1013 \
  --build-pytorch-vision --build-pytorch-audio \
  --use-ccache --release-type prerelease \
  --output-dir /therock/output/torch-wheels
'
}

stage_wheelhouse() {
    # Exact versions: unpinned, pip prefers the newer CUDA torch from PyPI.
    run wheelhouse '
WH=/therock/output/wheelhouse
rm -rf $WH && mkdir -p $WH
D=/therock/output/packages/dist
cp $D/rocm_sdk_core-*.whl $D/rocm_sdk_libraries-*.whl $D/rocm_sdk_device_gfx1013-*.whl /therock/output/torch-wheels/*.whl $WH/
$PY -m pip wheel -q --no-deps -w $WH $D/rocm-*.tar.gz
rocm_version=$(ls $D/rocm-*.tar.gz | sed "s|.*/rocm-||;s|\.tar\.gz$||")
$PY -m pip download -q --only-binary=:all: --find-links $WH --dest $WH \
  "rocm[libraries,device]==$rocm_version" \
  $(cd /therock/output/torch-wheels && ls *.whl | sed "s|^\([^-]*\)-\([^-]*\)-.*|\1==\2|")
cd $WH && sha256sum *.whl > SHA256SUMS && echo "$BUILD_ID" > BUILD_ID
ls -la $WH
'
}

(( $# )) || set -- all
for stage in "$@"; do
    case "$stage" in
        sources|rocm|wheels|torch|wheelhouse) "stage_$stage" ;;
        all) for s in sources rocm wheels torch wheelhouse; do "stage_$s"; done ;;
        build-id) build_id ;;
        shell) TTY="-it" run shell 'exec bash' ;;
        *) echo "usage: $0 [sources|rocm|wheels|torch|wheelhouse|all|build-id|shell]..." >&2; exit 2 ;;
    esac
done
