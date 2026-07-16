#!/bin/sh
# Wheel build script executed INSIDE the builder container. The host
# build_wheel.sh / build_wheel.bat starts the container with the project
# mounted at /work, so the resulting wheel is written straight to ./dist on
# the host.
set -e
cd /work

# Keep the heavy CMake object-file I/O on the container's fast local
# filesystem instead of the mounted host tree; only the final basisu binary
# and the wheel touch the mount.
export BASISU_BUILD_DIR=/tmp/basisu_build

python -m build --wheel --no-isolation --outdir dist