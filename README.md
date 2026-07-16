# Starlight App Builder

This is a project which contains the build dependencies for a starlight application.

## Install

The basisu texture encoder is compiled from the bundled
`extern/BasisUniversal` submodule during install, so CMake and a C++ compiler
are required on the host.

```
git submodule update --init -- extern/BasisUniversal
python -m pip install .
```

The compiled `basisu` binary is embedded in the wheel and resolved
automatically at runtime, so `prep-media` no longer requires a `-deps`
argument. Pass `-deps` only to override the bundled binary with a locally
built one.

## Building a wheel for a remote machine

The compile step only runs when the wheel is *built*, not when it is
*installed*. Build the wheel once on a machine with Docker and ship the
resulting `.whl` to a remote that has only Python.

Per-target Dockerfiles in `dist/` provision a **builder image** (CMake,
compiler, Python build tooling) - they do not contain the project. The build
itself runs inside a container started from that image with the project
mounted at `/work` (via `dist/build_inside.sh`), so the wheel is written
straight to `./dist` on the host. Targets:

- `ubuntu` - `dist/Dockerfile.ubuntu` (Ubuntu 22.04)
- `rocky` - `dist/Dockerfile.rocky` (Rocky Linux 9)

```
build_wheel.bat ubuntu      :: Windows (default target)
build_wheel.bat rocky
./build_wheel.sh rocky      :: Linux/macOS
```

Add more targets by dropping a `dist/Dockerfile.<name>` in place; the scripts
discover it automatically. On the remote:

```
pip install StarAppBuilder-<version>-<tag>.whl
```

No CMake or compiler is needed on the remote. The chosen Dockerfile's base
image must match the remote's distro/glibc generation; otherwise the bundled
`basisu` binary may fail to run.