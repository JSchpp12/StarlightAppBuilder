"""Hatchling build hook that compiles BasisUniversal during wheel build.

Running ``pip install`` (or ``python -m build``) builds the ``basisu``
executable from the bundled ``extern/BasisUniversal`` submodule via CMake and
embeds it in the wheel as ``star_app_builder/bin/<basisu>``. At runtime the
package resolves the bundled binary.

Requires CMake and a C++ compiler on the host (expected for this tool).
"""

import os
import shutil
import subprocess
import sys
import sysconfig

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "basisu"

    # Directories we will look in for an already-built binary before building
    # (e.g. produced by init.bat/init.sh). The binary BasisUniversal emits
    # lives in extern/BasisUniversal/bin, but those init scripts copy it into
    # deps/BasisUniversal/bin, so we reuse from there to skip a rebuild.
    _REUSE_DIRS = ("deps/BasisUniversal/bin", "extern/BasisUniversal/build")

    # Native executables BasisUniversal's build emits into <source>/bin. We
    # wipe these before building so a stale or wrong-platform binary from a
    # previous run (or copied into Docker from the host tree) is never picked
    # up or shipped.
    _BIN_ARTIFACTS = (
        "basisu", "basisu.exe",
        "example", "example.exe",
        "example_capi", "example_capi.exe",
        "example_transcoding", "example_transcoding.exe",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Disposable artifacts created by this hook, cleaned up in finalize().
        self._build_dir_to_clean = None
        self._built_binary_to_clean = None

    def initialize(self, version, build_data):
        # The wheel carries a native basisu binary, so it is NOT pure Python.
        # Force a platform-specific tag (e.g. py3-none-linux_x86_64) so pip
        # rejects the wheel on a mismatched OS/arch instead of installing a
        # binary that cannot run there. hatchling does not infer this from
        # pure_python alone, so we set the tag explicitly.
        build_data["pure_python"] = False
        build_data["infer_tag"] = False
        platform_tag = sysconfig.get_platform().replace(".", "_").replace("-", "_")
        build_data["tag"] = f"py3-none-{platform_tag}"

        root = self.root
        source_dir = os.path.join(root, "extern", "BasisUniversal")

        if not os.path.isfile(os.path.join(source_dir, "CMakeLists.txt")):
            # Likely a fresh clone without the submodule initialized. Try to
            # init it; if that fails (e.g. building from an sdist with no .git)
            # surface a clear error.
            if not self._try_init_submodule(root):
                raise RuntimeError(
                    "BasisUniversal source is missing. Run "
                    "`git submodule update --init -- extern/BasisUniversal` "
                    "before building, or build from a full checkout."
                )

        build_dir = os.environ.get(
            "BASISU_BUILD_DIR", os.path.join(source_dir, "build_dist")
        )

        binary = self._find_existing_binary(root)
        if binary is None:
            binary = self._build_basisu(source_dir, build_dir)

        if binary is None or not os.path.isfile(binary):
            raise RuntimeError("BasisUniversal build did not produce a basisu binary")

        force_include = build_data.setdefault("force_include", {})
        dest = os.path.join("star_app_builder", "bin", os.path.basename(binary))
        force_include[binary] = dest
        return build_data

    def finalize(self, version, build_data, artifact):
        # The wheel has now been assembled (the binary was copied in), so it is
        # safe to remove the disposable build artifacts. Leftover CMake caches
        # and stale binaries here are what break reinstalls, so we do not leave
        # them behind.
        if self._build_dir_to_clean:
            shutil.rmtree(self._build_dir_to_clean, ignore_errors=True)
        if self._built_binary_to_clean:
            try:
                os.remove(self._built_binary_to_clean)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _try_init_submodule(root):
        if not os.path.isdir(os.path.join(root, ".git")):
            return False
        try:
            subprocess.run(
                ["git", "submodule", "update", "--init", "--", "extern/BasisUniversal"],
                cwd=root,
                check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False
        return os.path.isfile(
            os.path.join(root, "extern", "BasisUniversal", "CMakeLists.txt")
        )

    def _find_existing_binary(self, root):
        """Reuse a binary produced by init.bat/init.sh, skipping a rebuild."""
        for rel in self._REUSE_DIRS:
            binary = self._binary_in_dir(os.path.join(root, rel))
            if binary:
                return binary
        return None

    @staticmethod
    def _binary_in_dir(directory):
        if not os.path.isdir(directory):
            return None
        names = (
            ("basisu.exe", "basisu")
            if sys.platform == "win32"
            else ("basisu", "basisu.exe")
        )
        # Release/ is where MSVC multi-config generators put the output.
        for sub in ("Release", ""):
            for name in names:
                candidate = os.path.join(directory, sub, name)
                if os.path.isfile(candidate):
                    return candidate
        return None

    @staticmethod
    def _clean_stale_bin_artifacts(bin_dir):
        if not os.path.isdir(bin_dir):
            return
        for name in CustomBuildHook._BIN_ARTIFACTS:
            try:
                os.remove(os.path.join(bin_dir, name))
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @staticmethod
    def _find_built_binary(source_dir, build_dir):
        # BasisUniversal's CMakeLists sets CMAKE_RUNTIME_OUTPUT_DIRECTORY to
        # <source>/bin, so that is where basisu actually lands. We also check
        # the build dir / its Release subdir as a fallback for generators that
        # ignore or override the output directory.
        search_dirs = (
            os.path.join(source_dir, "bin"),
            build_dir,
            os.path.join(build_dir, "Release"),
        )
        names = (
            ("basisu.exe", "basisu")
            if sys.platform == "win32"
            else ("basisu", "basisu.exe")
        )
        for directory in search_dirs:
            if not os.path.isdir(directory):
                continue
            for name in names:
                candidate = os.path.join(directory, name)
                if os.path.isfile(candidate):
                    return candidate
        return None

    def _build_basisu(self, source_dir, build_dir):
        # Always start from a clean CMake build directory. pip builds in an
        # isolated environment whose paths change every run; a stale
        # CMakeCache.txt referencing the previous env's toolchain is what makes
        # reinstalls fail to produce a basisu binary.
        if os.path.isdir(build_dir):
            shutil.rmtree(build_dir, ignore_errors=True)
        os.makedirs(build_dir, exist_ok=True)

        # Remove any previously-built native executables from <source>/bin so a
        # stale or wrong-platform binary is never mistaken for a fresh build.
        self._clean_stale_bin_artifacts(os.path.join(source_dir, "bin"))

        config_args = [
            "cmake",
            "-S",
            source_dir,
            "-B",
            build_dir,
            "-DCMAKE_CXX_STANDARD=17",
        ]
        # Single-config generators (Make/Ninja) need the build type at configure
        # time; multi-config generators (MSVC) ignore it and use --config later.
        if sys.platform != "win32":
            config_args.append("-DCMAKE_BUILD_TYPE=Release")

        subprocess.run(config_args, check=True)
        subprocess.run(
            ["cmake", "--build", build_dir, "--config", "Release", "--parallel"],
            check=True,
        )

        self._build_dir_to_clean = build_dir
        binary = self._find_built_binary(source_dir, build_dir)
        if binary is not None:
            self._built_binary_to_clean = binary
        return binary