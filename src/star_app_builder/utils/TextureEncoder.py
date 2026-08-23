import subprocess
import argparse
import json
import os
import shutil
import struct
import sys
import tempfile

from tqdm import tqdm

from star_app_builder.common import MediaPath
from star_app_builder.common import get_bundled_basisu_path

from .Ktx2Format import (
    KTX2_IDENTIFIER,
    KTX2_HEADER_SIZE,
    KTX2_LEVEL_INDEX_ENTRY_SIZE,
    KTX2_LEVEL_COUNT_OFFSET,
    KTX2_BLOCK_FIELDS,
    BASIS_SIG,
    BASIS_MIN_HEADER_SIZE,
    BASIS_HEADER_SIZE_FIELD_OFFSET,
    BASIS_DATA_SIZE_FIELD_OFFSET,
)

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

# Name of the per-run staging directory basisu writes into before files are
# atomically promoted to the real output tree. It lives directly under the
# output directory so os.replace() is an atomic same-volume rename. See
# TextureCompressor.compress() for the interrupt-safety rationale.
STAGING_DIR_NAME = ".basisu_staging"

def is_complete_ktx2(path: str) -> bool:
    """Heuristic completeness check for a .ktx2 file.

    Returns True only if the file starts with the KTX2 magic, the header and
    level index are fully present, and every byte extent declared in the header
    and level index fits within the actual file size. This catches truncation
    (the interrupted-compression failure mode) but does NOT validate the
    compressed payload itself, so it is a *necessary* signal, not a sufficient
    one. It is only used as a rescue for files already left in the output tree
    by older, non-atomic runs; going forward, atomic staging is the source of
    truth for "compression finished". Any read/parse error returns False so the
    caller re-compresses rather than shipping a suspect file.

    Known limitation: if basisu ever wrote level data out of the on-disk order
    implied by the index (it does not for the current encoder), a truncated
    file could theoretically still satisfy these bounds. The atomic-staging
    path makes this moot for new files; this check only guards legacy state.
    """
    try:
        file_size = os.path.getsize(path)
        if file_size < KTX2_HEADER_SIZE:
            return False
        with open(path, "rb") as f:
            header = f.read(KTX2_HEADER_SIZE)
        if len(header) < KTX2_HEADER_SIZE or header[:12] != KTX2_IDENTIFIER:
            return False

        level_count = struct.unpack_from("<I", header, KTX2_LEVEL_COUNT_OFFSET)[0]
        num_levels = max(1, level_count)

        index_size = num_levels * KTX2_LEVEL_INDEX_ENTRY_SIZE
        if file_size < KTX2_HEADER_SIZE + index_size:
            return False

        with open(path, "rb") as f:
            f.seek(KTX2_HEADER_SIZE)
            level_index = f.read(index_size)
        if len(level_index) < index_size:
            return False

        # Every declared level must be fully contained within the file. The
        # base level (index 0, largest) is stored last on disk, so a truncation
        # that cut the write short fails this bound.
        for i in range(num_levels):
            off = i * KTX2_LEVEL_INDEX_ENTRY_SIZE
            byte_offset, byte_length = struct.unpack_from("<QQ", level_index, off)
            if byte_length > 0 and byte_offset + byte_length > file_size:
                return False

        # The optional data blocks (dfd / kvd / sgd) must also fit.
        for field_offset, size_bytes in KTX2_BLOCK_FIELDS:
            if size_bytes == 4:
                block_offset, block_length = struct.unpack_from(
                    "<II", header, field_offset
                )
            else:
                block_offset, block_length = struct.unpack_from(
                    "<QQ", header, field_offset
                )
            if block_length > 0 and block_offset + block_length > file_size:
                return False

        return True
    except (OSError, struct.error, ValueError):
        return False

def is_complete_basis(path: str) -> bool:
    """Heuristic completeness check for a .basis file.

    Validates the signature and that the declared header + data size fits
    within the actual file size. Same caveats as is_complete_ktx2: it catches
    truncation, not payload corruption, and fails safe (False) on any error.
    """
    try:
        file_size = os.path.getsize(path)
        if file_size < BASIS_MIN_HEADER_SIZE:
            return False
        with open(path, "rb") as f:
            head = f.read(BASIS_MIN_HEADER_SIZE)
        if len(head) < BASIS_MIN_HEADER_SIZE or head[:2] != BASIS_SIG:
            return False
        header_size = struct.unpack_from("<H", head, BASIS_HEADER_SIZE_FIELD_OFFSET)[0]
        data_size = struct.unpack_from("<I", head, BASIS_DATA_SIZE_FIELD_OFFSET)[0]
        if header_size < BASIS_MIN_HEADER_SIZE:
            return False
        # A complete .basis is header_size + data_size bytes (extended data is
        # already accounted for in data_size). Truncation makes it smaller.
        if file_size < header_size + data_size:
            return False
        return True
    except (OSError, struct.error, ValueError):
        return False

def is_output_complete(output_path: str, media_path) -> bool:
    """Dispatch to the format-specific completeness checker.

    Returns True for unknown/non-compressed extensions so callers that
    conservatively invoke this do not spuriously re-encode files they cannot
    validate. The authoritative signal for new files is atomic promotion into
    the output directory (see TextureCompressor.compress); this is a rescue
    check for files already sitting in the tree.
    """
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".ktx2":
        return is_complete_ktx2(output_path)
    if ext == ".basis":
        return is_complete_basis(output_path)
    return True

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
        # walking the whole subtree. The .star_ignore_<stem> marker is a
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

        # basisu writes each texture's .ktx2/.basis straight into -output_path.
        # To make "file present in the output dir" a reliable "compression
        # finished" signal (so an interrupted cluster run can never leave a
        # truncated file in the real output tree), basisu is pointed at a
        # staging directory that lives under output_dir (same volume ->
        # os.replace is atomic) and each batch's files are only promoted after
        # its subprocess exits cleanly. Partial files from a killed run stay in
        # staging and are discarded on the next run.
        staging_root = os.path.join(output_dir, STAGING_DIR_NAME)
        # Discard any partials left behind by a previously interrupted run.
        shutil.rmtree(staging_root, ignore_errors=True)

        total_files = sum(len(t) for t in self.rel_media_dir_to_textures.values())
        if total_files == 0:
            return

        if batch_size is None:
            batch_size = (os.cpu_count() or 1) * 4

        if log_path is None:
            log_path = os.path.join(os.getcwd(), "compression_log.txt")
            print(f"BasisU compression output is being logged to: {log_path}")
        log_handle = open(log_path, "w", encoding="utf-8", errors="replace")

        progress = tqdm(
            total=total_files, unit=" textures", desc="Compressing textures"
        )
        batch_id = 0
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
                    "-uastc",
                    "-individual",
                    "-mipmap",
                    "-parallel",
                ]

                if max_threads is not None and max_threads > 0:
                    base_command += ["-max_threads", str(max_threads)]

                if self.use_bases_file_type:
                    base_command.append("-basis")

                # Resolve the basisu -quality value. An explicit --quality
                # preset (high/medium/low) wins; otherwise fall back to the
                # legacy --fastest speed mode (25) or the default max (100).
                if quality is not None:
                    quality_value = _QUALITY_PRESETS[quality]
                elif use_compress_speed_fastest:
                    quality_value = 25
                else:
                    quality_value = 100
                base_command.append("-quality")
                base_command.append(str(quality_value))

                full_output = output_dir
                if rel_output_dir is not None:
                    full_output = os.path.join(output_dir, rel_output_dir)
                os.makedirs(full_output, exist_ok=True)

                # NOTE: -output_path is set per batch below to point at that
                # batch's staging directory, not at full_output.

                if not textures:
                    continue

                # Batch the MediaPath objects (not just their input paths) so we
                # know each batch's expected output filenames for promotion.
                chunks = list(TextureCompressor.batch_list(textures, batch_size))

                for batch in chunks:
                    if not batch:
                        continue
                    staging_batch_dir = os.path.join(staging_root, f"batch_{batch_id}")
                    batch_id += 1
                    os.makedirs(staging_batch_dir, exist_ok=True)

                    listing_fd, listing_path = tempfile.mkstemp(
                        suffix=".txt", prefix="basisu_inputs_", text=True
                    )
                    try:
                        with os.fdopen(listing_fd, "w", encoding="utf-8") as lf:
                            for t in batch:
                                lf.write(t.full_input_path)
                                lf.write("\n")
                        batch_command = base_command + [
                            "-output_path",
                            os.path.abspath(staging_batch_dir),
                            "@" + listing_path,
                        ]
                        subprocess.run(
                            batch_command,
                            cwd=self.basis_u_dir,
                            check=True,
                            text=True,
                            stdout=log_handle,
                            stderr=subprocess.STDOUT,
                        )
                    except subprocess.CalledProcessError as e:
                        print("Error occurred during texture compression:")
                        print(e)
                        print(f"See basisu log for details: {log_path}")
                        raise Exception("Failed to compress textures")
                    finally:
                        try:
                            os.remove(listing_path)
                        except OSError:
                            pass

                    # Promote each expected output file from staging into the
                    # real output directory. os.replace is atomic on the same
                    # volume (staging lives under output_dir) and overwrites any
                    # stale file at the destination. If basisu exited 0 but a
                    # file is unexpectedly absent, warn and leave it missing so
                    # the next run re-compresses it (fail-safe toward redo).
                    for t in batch:
                        staging_file = os.path.join(
                            staging_batch_dir, t.output_file_base
                        )
                        if os.path.exists(staging_file):
                            final_file = os.path.join(full_output, t.output_file_base)
                            os.replace(staging_file, final_file)
                        else:
                            print(
                                f"Warning: basisu reported success but did not "
                                f"produce expected output: {t.output_file_base}"
                            )

                    # Drop the batch's staging dir (and any stragglers) now that
                    # its files have been promoted.
                    shutil.rmtree(staging_batch_dir, ignore_errors=True)

                    # We don't parse basisu's per-file progress; just advance
                    # the bar by the size of the batch we just handed off.
                    progress.update(len(batch))

            # Every batch completed and promoted; remove the now-empty staging
            # tree so a clean run leaves no .basisu_staging behind. This only
            # runs on full success: an exception above propagates to finally
            # and skips this, leaving staging in place for the next run to
            # clear at the top of compress().
            shutil.rmtree(staging_root, ignore_errors=True)
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
