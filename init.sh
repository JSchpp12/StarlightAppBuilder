#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python -m pip install .

mkdir -p ${SCRIPT_DIR}/extern/BasisUniversal
cd ${SCRIPT_DIR}/extern/BasisUniversal
rm -rf build
mkdir -p build
cd build

cmake -DCMAKE_CXX_STANDARD=17 -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --config Release

mkdir -p "${SCRIPT_DIR}/deps"
mkdir -p "${SCRIPT_DIR}/deps/BasisUniversal"
mkdir -p "${SCRIPT_DIR}/deps/BasisUniversal/bin"

cp -r "${SCRIPT_DIR}/extern/BasisUniversal/bin" "${SCRIPT_DIR}/deps/BasisUniversal/"
if [[ -d "${SCRIPT_DIR}/extern/BasisUniversal/build/Release" ]]; then
    cp -r "${SCRIPT_DIR}extern/BasisUniversal/build/Release" "${SCRIPT_DIR}/deps/BasisUniversal/"
fi