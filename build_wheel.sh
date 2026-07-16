#!/bin/sh
# Build a StarAppBuilder wheel inside a Docker builder image matching the
# remote target. The builder image only provisions the toolchain; the actual
# wheel build runs in a container with the project mounted at /work, so the
# wheel lands directly in ./dist on the host. POSIX sh compatible (sh + bash).
#
# Usage:
#   ./build_wheel.sh [target]    target defaults to "ubuntu"
#
# A target maps to dist/Dockerfile.<target>. Add more by dropping a
# dist/Dockerfile.<name> in place; the script discovers it automatically.
set -e

TARGET="${1:-ubuntu}"
IMAGE_TAG="starappbuilder-builder-${TARGET}"
DOCKERFILE="dist/Dockerfile.${TARGET}"

if [ ! -f "$DOCKERFILE" ]; then
    echo "No Dockerfile for target '${TARGET}' (looked for ${DOCKERFILE})." >&2
    echo "Available targets:" >&2
    ls -1 dist/Dockerfile.* 2>/dev/null | sed 's#dist/Dockerfile\.##' >&2
    exit 1
fi

echo "==> Ensuring BasisUniversal submodule is present"
git submodule update --init -- extern/BasisUniversal

echo "==> Building builder image: ${IMAGE_TAG} (${DOCKERFILE})"
# The Dockerfile only provisions tooling (no project COPY), so pipe it via
# stdin to avoid sending the source tree as build context.
docker build -t "$IMAGE_TAG" - < "$DOCKERFILE"

echo "==> Building wheel inside container (project mounted at /work)"
docker run --rm -v "$PWD:/work" "$IMAGE_TAG" sh /work/dist/build_inside.sh

echo "==> Done. Wheel(s) in ./dist:"
ls -1 dist/*.whl 2>/dev/null || echo "  (no wheel found - check build output above)"