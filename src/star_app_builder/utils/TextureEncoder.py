import subprocess
import argparse
import json
import os
import sys
import tempfile

from tqdm import tqdm

from star_app_builder.common import MediaPath
from star_app_builder.common import get_bundled_basisu_path

# The authoritative set of extensions eligible for texture compression.
# Is_File_A_Image decides purely by extension (an O(1) string check with no
# disk I/O and no Pillow dependency), so this set also defines the routing
# policy: listed extensions are treated as images and handed to the encoder;
# everything else is copied as-is.
#
# This preserves the original routing behaviour, which was an accident of what
# Pillow could open: .exr / .hdr / .ktx2 returned False (Pillow cannot open
# them by default) and were copied, so they are intentionally NOT listed here.
# Add them here if you want them compressed (basisu supports UASTC HDR).
_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".gif",
    ".tif",
    ".tiff",
    ".webp",
    ".tga",
    ".basis",
}

# Named quality presets for the -quality CLI flag. basisu's -quality ranges
# from 1 to 100; these map the user-facing levels to encoder values. When no
# preset is requested, compress() falls back to the legacy behaviour: 25 for
# the --fastest speed mode, otherwise 100 (max). "lossless" is an explicit
# name for that max (100) so callers can state their intent without relying on
# the implicit default.
_QUALITY_PRESETS = {
    "lossless": 100,
    "high": 90,
    "medium": 75,
    "low": 50,
}

# Per-run cache so the ignore-marker lookup runs at most once per file.
_should_compress_cache = {}


class TextureCompressor:
    @staticmethod
    def search_for_file(file_path: str, texture_root_dir):
        for ele in os.listdir(texture_root_dir):
            search_ele = os.path.join(texture_root_dir, ele)
            if os.path.isdir(search_ele):
                deep_search = TextureCompressor.search_for_file(file_path, search_ele)
                if deep_search is not None:
                    return deep_search
            else:
                if file_path in ele:
                    return search_ele

        return None

    @staticmethod
    def search_for_star_ignore(texture_path: MediaPath) -> None:
        # Look only in the texture's own directory rather than recursively
        # walking the whole subtree. The `.star_ignore_<stem>` marker is a
        # per-texture flag, so a single directory listing is sufficient and
        # avoids an O(tree size) scan per image.
        name_to_find = f".star_ignore_{texture_path.Get_Output_Stem()}"
        texture_dir = os.path.dirname(texture_path.full_input_path)
        if not texture_dir or not os.path.isdir(texture_dir):
            return None
        candidate = os.path.join(texture_dir, name_to_find)
        return candidate if os.path.isfile(candidate) else None

    @staticmethod
    def get_compressed_file_name(
        texture_info: MediaPath, use_basis_file_format: bool = False
    ) -> str:
        if use_basis_file_format:
            return texture_info.Get_Output_Stem() + ".basis"
        else:
            return texture_info.Get_Output_Stem() + ".ktx2"

    @staticmethod
    def should_compress(texture: MediaPath) -> bool:
        # Memoized per input path: the ignore-marker lookup only needs to run
        # once per file even though should_compress is called multiple times
        # for the same texture during a single run.
        key = os.path.abspath(texture.full_input_path)
        cached = _should_compress_cache.get(key)
        if cached is not None:
            return cached
        result = TextureCompressor.search_for_star_ignore(texture) is None
        _should_compress_cache[key] = result
        return result

    @staticmethod
    def batch_list(lst, batch_size):
        """Split list into batches of specified size."""
        for i in range(0, len(lst), batch_size):
            yield lst[i : i + batch_size]

    @staticmethod
    def _resolve_basis_u_exe(basis_u_dir):
        """Locate the basisu executable within the given directory."""
        names = (
            ("basisu.exe", "basisu")
            if sys.platform == "win32"
            else ("basisu", "basisu.exe")
        )
        for name in names:
            candidate = os.path.join(basis_u_dir, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    def __init__(
        self, basis_u_dir: str = None, use_basis_file_type: bool = False
    ) -> None:
        self.rel_media_dir_to_textures = {}
        self.use_bases_file_type = use_basis_file_type

        if basis_u_dir is not None:
            # Explicit deps directory provided on the command line.
            if not os.path.isdir(basis_u_dir):
                raise Exception("Provided directory to basis_u does not exist")
            self.basis_u_dir = basis_u_dir
            self.basis_u_exe = TextureCompressor._resolve_basis_u_exe(basis_u_dir)
            if self.basis_u_exe is None:
                raise Exception(
                    f"basisu executable not found in provided deps dir: {basis_u_dir}"
                )
        else:
            # Fall back to the binary bundled into the wheel at install time.
            self.basis_u_exe = get_bundled_basisu_path()
            if self.basis_u_exe is None:
                raise Exception(
                    "No basisu executable was bundled with this install and no "
                    "-deps directory was provided. Reinstall the package or pass "
                    "-deps pointing at a directory containing basisu."
                )
            self.basis_u_dir = os.path.dirname(self.basis_u_exe)

    def add_texture(self, texture: MediaPath) -> None:
        if texture.relative_media_path_parent not in self.rel_media_dir_to_textures:
            self.rel_media_dir_to_textures[texture.relative_media_path_parent] = []
        self.rel_media_dir_to_textures[texture.relative_media_path_parent].append(
            texture
        )

    def compress(
        self,
        output_dir,
        use_compress_speed_fastest: bool,
        batch_size: int = None,
        quality: str = None,
        max_threads: int = None,
        log_path: str = None,
    ) -> None:
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)

        total_files = sum(len(t) for t in self.rel_media_dir_to_textures.values())
        if total_files == 0:
            return

        if batch_size is None:
            # Default to ~two compression waves per batch: double the hardware
            # thread count, so -parallel has a little extra work queued per
            # process and the progress bar advances at a comfortable cadence.
            # os.cpu_count() can return None on exotic platforms, so fall back
            # to 1 before doubling.
            batch_size = (os.cpu_count() or 1) * 4

        if log_path is None:
            log_path = os.path.join(os.getcwd(), 'compression_log.txt')
            print(f'BasisU compression output is being logged to: {log_path}')
        log_handle = open(log_path, 'w', encoding='utf-8', errors='replace')

        progress = tqdm(total=total_files, unit=' textures', desc='Compressing textures')
        try:
            for rel_output_dir, textures in self.rel_media_dir_to_textures.items():
                # -parallel makes basisu compress multiple textures
                # simultaneously, one per thread, instead of one at a time. With
                # -individual (the default) each input still gets its own output
                # file; -parallel just spreads the per-file work across cores,
                # which is the single biggest speedup available without
                # changing output quality.
                base_command = [
                    self.basis_u_exe,
                    '-uastc',
                    '-individual',
                    '-mipmap',
                    '-parallel',
                ]

                if max_threads is not None and max_threads > 0:
                    base_command += ['-max_threads', str(max_threads)]

                if self.use_bases_file_type:
                    base_command.append('-basis')

                # Resolve the basisu -quality value. An explicit --quality
                # preset (high/medium/low) wins; otherwise fall back to the
                # legacy --fastest speed mode (25) or the default max (100).
                if quality is not None:
                    quality_value = _QUALITY_PRESETS[quality]
                elif use_compress_speed_fastest:
                    quality_value = 25
                else:
                    quality_value = 100
                base_command.append('-quality')
                base_command.append(str(quality_value))

                full_output = output_dir
                if rel_output_dir is not None:
                    full_output = os.path.join(output_dir, rel_output_dir)
                os.makedirs(full_output, exist_ok=True)

                base_command += ['-output_path', os.path.abspath(full_output)]

                texture_paths = [t.full_input_path for t in textures]
                if not texture_paths:
                    continue

                # Hand basisu each batch via a listing file (@path): basisu reads one
                # filename per line, which sidesteps the Windows command-line
                # length limit. Each batch holds ~one wave of inputs (by default
                # the hardware thread count), so -parallel saturates the cores
                # for that batch and the progress bar ticks once per wave. A
                # caller can still pass an explicit batch_size to chunk finer or
                # coarser.
                chunks = list(TextureCompressor.batch_list(texture_paths, batch_size))

                for batch in chunks:
                    if not batch:
                        continue
                    listing_fd, listing_path = tempfile.mkstemp(
                        suffix='.txt', prefix='basisu_inputs_', text=True
                    )
                    try:
                        with os.fdopen(listing_fd, 'w', encoding='utf-8') as lf:
                            for p in batch:
                                lf.write(p)
                                lf.write('\n')
                        batch_command = base_command + ['@' + listing_path]
                        subprocess.run(
                            batch_command,
                            cwd=self.basis_u_dir,
                            check=True,
                            text=True,
                            stdout=log_handle,
                            stderr=subprocess.STDOUT,
                        )
                    except subprocess.CalledProcessError as e:
                        print('Error occurred during texture compression:')
                        print(e)
                        print(f'See basisu log for details: {log_path}')
                        raise Exception('Failed to compress textures')
                    finally:
                        try:
                            os.remove(listing_path)
                        except OSError:
                            pass
                    # We don't parse basisu's per-file progress; just advance
                    # the bar by the size of the batch we just handed off.
                    progress.update(len(batch))
        finally:
            progress.close()
            log_handle.close()


def Is_File_A_Image(media_file: str) -> bool:
    ext = os.path.splitext(media_file)[1].lower()
    return ext in _IMAGE_EXTENSIONS


def Generate_Media_File_For_Image(media_file: str, subDir: str) -> MediaPath:
    media_file_path = MediaPath(media_file, subDir)

    if TextureCompressor.should_compress(media_file_path):
        media_file_path.output_file_base = TextureCompressor.get_compressed_file_name(
            media_file_path
        )
    return media_file_path


def Create_Media_Path(full_media_path: str, subDir: str) -> MediaPath:
    if Is_File_A_Image(full_media_path):
        return Generate_Media_File_For_Image(full_media_path, subDir)
    else:
        return MediaPath(full_media_path, subDir)
