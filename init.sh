#! bin/bash

mkdir extern/BasisUniversal/build

cd extern/BasisUniversal/build

cmake -DCMAKE_CXX_STANDARD=17 -DCMAKE_BUILD_TYPE=Release ..

cmake --build . --config Release -j 6

cd ../../../

mkdir deps
mkdir deps/BasisUniversal
mkdir deps/BasisUniversal/bin

cp -r ./extern/BasisUniversal/bin ./deps/BasisUniversal/bin
cp -r ./extern/BasisUniversal/build/Release ./deps/BasisUniversal/