@echo off

git submodule init
git submodule update

set original_dir=%cd%
set build_dir=build
set final_basis_dir=deps/BasisUniversal
set basis_dir=extern/BasisUniversal
set basis_build_dir=%basis_dir%/build
if not exist "deps" mkdir "deps"
if not exist "%basis_build_dir%" mkdir "%basis_build_dir%"
if not exist "%final_basis_dir%" mkdir "%final_basis_dir%"

cd "%basis_build_dir%"

echo Building Basis Universal
cmake -DCMAKE_CXX_STANDARD=17 -DCMAKE_BUILD_TYPE=Release ..

echo Compiling Basis Universal...
cmake --build . --config Release -j 6

cd %original_dir%

echo "%basis_build_dir%\Release\*"
if not exist "%final_basis_dir%\bin" mkdir "%final_basis_dir%\bin"
if not exist "%final_basis_dir%\Release" mkdir "%final_basis_dir%\Release"
xcopy /E /I /Y "%basis_dir%\bin\*" "%final_basis_dir%\bin"
xcopy /E /I /Y "%basis_build_dir%\Release\*" "%final_basis_dir%\Release\"
