#!/bin/bash
mkdir -p extern/BasisUniversal
cd extern/BasisUniversal
rm -rf build
mkdir -p build
cd build

cmake -DCMAKE_CXX_STANDARD=17 -DCMAKE_BUILD_TYPE=Release ..
cmake --build . --config Release

cd ../../../
mkdir -p deps
mkdir -p deps/BasisUniversal
mkdir -p deps/BasisUniversal/bin

cp -r ./extern/BasisUniversal/bin ./deps/BasisUniversal/
if [[ -d "extern/BasisUniversal/build/Release" ]]; then
    cp -r ./extern/BasisUniversal/build/Release ./deps/BasisUniversal/
fi