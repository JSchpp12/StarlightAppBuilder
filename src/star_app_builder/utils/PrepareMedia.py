import json
import os
import string
import shutil
import argparse
import filecmp

from tqdm import tqdm

from .TextureEncoder import TextureCompressor
from .TextureEncoder import Is_File_A_Image
from .TextureEncoder import Create_Media_Path
from .TextureEncoder import STAGING_DIR_NAME
from .TextureEncoder import is_output_complete
from .MediaSidecar import (
    PREP_COMPRESS,
    PREP_COPY,
    Download_Media_File,
    Get_Download_Failure_Count,
    Get_Media_Name_From_Sidecar,
    Get_Sidecar_Path,
    Is_Hidden_File,
    Is_Sidecar_File,
    Is_URL_Source,
    Load_Sidecar,
    Register_Media,
    Reset_Registry,
    Validate_Sidecar,
    Write_Default_Sidecar,
)
from star_app_builder.common import MediaPath
from .PrepareEngineConfig import main as mainPrepConfig


def GetSubMediaPathFromFullMediaPath(fullMediaPath: string) -> string:
    return fullMediaPath.split("media\\")[-1]


def CopyFile(destination_dir: string, file_path: MediaPath) -> None:
    full_destination_path = os.path.abspath(
        os.path.join(destination_dir, file_path.Get_Output_Media_Rel_Path())
    )

    try:
        shutil.copy2(file_path.full_input_path, full_destination_path)
    except Exception as e:
        print(f"Failed to copy file.")
        print(f"Source: {file_path.full_input_path}")
        print(f"Destination: {full_destination_path}")
        print(e)


def CheckForFileInDirectory(file_to_find, search_directory) -> bool:
    for ele in os.listdir(search_directory):
        if file_to_find in ele:
            return True
    return False


# copy media as needed
def FindContents(currentPath: string):
    contents = set()

    for dir in os.listdir(currentPath):
        if "." != dir[0]:
            fullPath = os.path.join(currentPath, dir)
            if os.path.isdir(fullPath):
                # is dir need to go deeper
                deepResults = FindContents(fullPath)
                contents.update(deepResults)
            else:
                contents.add(fullPath)

    return contents


def BuildDirectoryIndex(root: str):
    """Walk `root` exactly once and bucket files by directory.

    Returns (immediate, all_files) where:
      immediate[abs_dir] -> set of absolute paths of files directly in that dir
      all_files          -> set of every file path under root (recursive)

    This replaces the per-directory recursive FindContents calls in processDir,
    which re-walked every ancestor's subtree and was O(N * depth). Per-directory
    *subtree* sets are intentionally NOT materialized here (that would itself be
    O(N * depth)); callers that need "everything under here" use all_files (a
    single root-level recursive set) or call FindContents ad-hoc on one subtree.
    """
    immediate = {}
    all_files = set()
    if not os.path.isdir(root):
        return immediate, all_files

    for dp, dirs, files in os.walk(root):
        # Never descend into the basisu staging tree: it holds partial
        # files from interrupted runs and must not be indexed as real
        # outputs (the staging dir is created under the output dir by
        # TextureCompressor.compress and is removed on a clean run).
        dirs[:] = [d for d in dirs if d != STAGING_DIR_NAME]
        dp_abs = os.path.abspath(dp)
        file_set = set()
        for f in files:
            p = os.path.abspath(os.path.join(dp, f))
            file_set.add(p)
            all_files.add(p)
        immediate[dp_abs] = file_set

    return immediate, all_files


def Resolve_Sidecars(in_immediate: dict) -> None:
    """Load, validate, download, and generate sidecars before the media walk.

    Pass 1 honours explicit ``<media filename>.star.json`` sidecars, downloading
    URL sources that are not cached yet. Pass 2 writes a default sidecar next to
    every media file that has none, expressing the legacy behaviour (compress
    images, copy everything else) as data. Ordinary ``.json`` files are media
    and are never treated as sidecars.

    Both passes populate the MediaSidecar registry, which is what
    ``TextureCompressor.should_compress`` consults during the walk.
    """
    for abs_dir in sorted(in_immediate):
        files = in_immediate[abs_dir]
        sidecars = sorted(
            f for f in files if Is_Sidecar_File(f) and not Is_Hidden_File(f)
        )
        media = sorted(
            f for f in files if not Is_Sidecar_File(f) and not Is_Hidden_File(f)
        )

        claimed = set()

        # Pass 1: explicit sidecars.
        for sidecar in sidecars:
            parsed = Load_Sidecar(sidecar)
            if parsed is None:
                continue
            data = Validate_Sidecar(parsed, sidecar)
            if data is None:
                continue

            # The sidecar's own filename names the media it describes (and,
            # for a URL source, the file to download into).
            target = os.path.abspath(
                os.path.join(abs_dir, Get_Media_Name_From_Sidecar(sidecar))
            )

            if target in claimed:
                print(
                    f"Warning: multiple sidecars claim "
                    f"'{os.path.basename(target)}'; ignoring "
                    f"{os.path.basename(sidecar)}."
                )
                continue

            source = data["source"]
            if Is_URL_Source(source):
                if not os.path.isfile(target):
                    print(f"Downloading {os.path.basename(target)} ...")
                    if not Download_Media_File(source, target):
                        # Leave the sidecar in place so the next run retries.
                        continue
                # Downloaded files participate in stale-output cleanup from
                # this run onward.
                in_immediate[abs_dir].add(target)

            if not os.path.isfile(target):
                print(
                    f"Warning: sidecar {os.path.basename(sidecar)} describes "
                    f"missing media: {target}"
                )
                continue

            media_type = data["type"]
            actual_type = os.path.splitext(target)[1].lstrip(".").lower()
            if actual_type and actual_type != media_type:
                print(
                    f"Warning: sidecar {os.path.basename(sidecar)} declares type "
                    f"'{media_type}' but '{os.path.basename(target)}' is "
                    f"'{actual_type}'; using the actual extension."
                )
                media_type = actual_type

            prep = data["prep"]
            if prep == PREP_COMPRESS and not Is_File_A_Image(target):
                print(
                    f"Warning: sidecar {os.path.basename(sidecar)} says compress "
                    f"for non-image '{media_type}'; treating as copy."
                )
                prep = PREP_COPY

            Register_Media(
                target,
                {"type": media_type, "source": source, "prep": prep},
            )
            claimed.add(target)

        # Pass 2: auto-generate defaults for unclaimed media files.
        for media_file in media:
            if media_file in claimed:
                continue

            # The sidecar name includes the media extension, so two files that
            # share a stem (skybox.png + skybox.mp4) get distinct sidecars and
            # never collide.
            own_sidecar = Get_Sidecar_Path(media_file)
            ext = os.path.splitext(media_file)[1].lstrip(".").lower()
            prep = PREP_COMPRESS if Is_File_A_Image(media_file) else PREP_COPY

            if not os.path.isfile(own_sidecar):
                Write_Default_Sidecar(
                    own_sidecar, ext, os.path.basename(media_file), prep
                )

            Register_Media(
                media_file,
                {"type": ext, "source": os.path.basename(media_file), "prep": prep},
            )


def RemoveOldFiles(subDir, inputMediaFiles, currentMediaFiles, destinationMediaDir):
    """Remove output files that no longer correspond to a current input file.

    Operates per-directory: inputMediaFiles and currentMediaFiles are the
    immediate (non-recursive) absolute-path file sets for the same logical
    subdir. The expected set of output paths is derived from the current
    inputs (input -> output via Create_Media_Path, which honours the sidecar's
    prep approach), and any existing output file not in that expected set is
    stale and removed.

    Sidecars and dotfiles are input-only metadata and are never expected in
    the output tree, so stale copies left there by older runs are removed.
    """
    expected_outputs = set()
    for in_file in inputMediaFiles:
        if Is_Hidden_File(in_file) or Is_Sidecar_File(in_file):
            continue
        media_path = Create_Media_Path(in_file, subDir)
        expected_outputs.add(
            os.path.abspath(
                os.path.join(
                    destinationMediaDir, media_path.Get_Output_Media_Rel_Path()
                )
            )
        )

    for out_file in currentMediaFiles:
        if out_file not in expected_outputs:
            try:
                os.remove(out_file)
            except OSError as e:
                print(f"Failed to remove stale output file.")
                print(f"File: {out_file}")
                print(e)


def RemoveEmptyDirectories(targetDirectory) -> None:
    for dir_path, sub_dir, file_names in os.walk(targetDirectory):

        if dir_path != targetDirectory and not sub_dir and not file_names:
            os.rmdir(dir_path)


def ProcessNewFiles(
    subDir,
    input_media_files,
    current_media_files,
    input_media_dir,
    destination_dir,
    compressor: TextureCompressor,
    progress: tqdm,
) -> None:
    for file in input_media_files:
        full_src_file = os.path.abspath(os.path.join(input_media_dir, os.pardir, file))

        base_name = os.path.basename(full_src_file)
        if Is_Hidden_File(base_name) or Is_Sidecar_File(base_name):
            # Sidecars are input-only metadata; never copied, never compressed.
            # Dotfiles (including interrupted-download temps) are not media.
            continue

        media_file_path = Create_Media_Path(full_src_file, subDir)
        # Normalize to an absolute path so the form matches the absolute
        # paths stored in current_media_files (built by BuildDirectoryIndex
        # via os.path.abspath). Without this, a relative destination_dir
        # yields a relative destination_comparison that never matches the
        # absolute set entries, so every file is wrongly treated as new and
        # reprocessed.
        destination_comparison = os.path.abspath(
            os.path.join(destination_dir, media_file_path.output_file_base)
        )
        if subDir is not None:
            destination_comparison = os.path.abspath(
                os.path.join(destination_dir, subDir, media_file_path.output_file_base)
            )

        if destination_comparison not in current_media_files:
            # check if directors need to be created
            if subDir is not None:
                result_dir = os.path.join(destination_dir, subDir)
                if not os.path.isdir(result_dir):
                    os.makedirs(result_dir)

            if Is_File_A_Image(full_src_file) and TextureCompressor.should_compress(
                media_file_path
            ):
                compressor.add_texture(media_file_path)
            else:
                CopyFile(destination_dir, media_file_path)
        elif (
            Is_File_A_Image(full_src_file)
            and TextureCompressor.should_compress(media_file_path)
            and not is_output_complete(destination_comparison, media_file_path)
        ):
            # The compressed output exists but is structurally incomplete -
            # the signature of a run interrupted mid-compression (before
            # atomic staging existed, or via a path that bypassed it).
            # Remove the partial file and re-queue it so basisu writes it
            # fresh into staging. Fail-safe: any header/IO error in the
            # verifier is treated as incomplete, so we re-compress rather
            # than ship a possibly-truncated texture.
            try:
                os.remove(destination_comparison)
            except OSError as e:
                print(f"Failed to remove incomplete compressed output.")
                print(f"File: {destination_comparison}")
                print(e)
            compressor.add_texture(media_file_path)
        elif (
            not Is_File_A_Image(full_src_file)
            and not filecmp.cmp(full_src_file, destination_comparison, shallow=False)
        ) or (
            Is_File_A_Image(full_src_file)
            and not TextureCompressor.should_compress(media_file_path)
            and not filecmp.cmp(full_src_file, destination_comparison, shallow=False)
        ):
            CopyFile(destination_dir, media_file_path)
        elif (
            Is_File_A_Image(full_src_file)
            and TextureCompressor.should_compress(media_file_path)
            and _source_newer_than_output(full_src_file, destination_comparison)
        ):
            # The compressed output already exists, but the source texture
            # has changed since it was last encoded (its mtime is newer than
            # the compressed file's). A byte-for-byte filecmp is meaningless
            # here (.png vs .ktx2/.basis), so the modification time is the
            # signal that the input no longer matches the output. Queue the
            # texture to be re-compressed; basisu overwrites the existing
            # output file in the final compress() pass.
            compressor.add_texture(media_file_path)

        progress.update()


def _source_newer_than_output(source_path: str, output_path: str) -> bool:
    """Return True when ``source_path`` was modified after ``output_path``.

    Used to decide whether a compressible texture needs re-encoding: a
    content comparison is impossible across formats (.png -> .ktx2), so the
    source's mtime is the change signal. Missing output or a clock skew
    where the output is at least as new as the source means no re-compress.
    """
    try:
        return os.path.getmtime(source_path) > os.path.getmtime(output_path)
    except OSError:
        # Output file missing (e.g. deleted out of band) or unreadable; let
        # the caller fall back to other handling rather than crashing.
        return False


def processDir(
    curDir,
    inDir: str,
    outDir: str,
    inConfigFilePath: str,
    fastestOption: bool,
    progress: tqdm,
    in_immediate: dict,
    out_immediate: dict,
    compressor: TextureCompressor,
):
    currentInDir = inDir
    if curDir is not None:
        currentInDir = os.path.join(inDir, curDir)

    if not os.path.isdir(currentInDir):
        print(
            "Attempted to process directory which does not exist or is not a directory"
        )

    currentOutDir = outDir
    if curDir is not None:
        currentOutDir = os.path.join(outDir, curDir)
    if not os.path.isdir(currentOutDir):
        os.mkdir(currentOutDir)

    files = []
    for ele in os.listdir(currentInDir):
        elePath = os.path.join(currentInDir, ele)
        if os.path.isdir(elePath):
            subInDir = ele
            if curDir is not None:
                subInDir = os.path.join(curDir, ele)

            processDir(
                subInDir,
                inDir,
                outDir,
                inConfigFilePath,
                fastestOption,
                progress,
                in_immediate,
                out_immediate,
                compressor,
            )
        else:
            # process file
            files.append(elePath)

    # Use the precomputed per-directory file sets instead of re-walking the
    # subtree (FindContents) at every level. The sets reflect the pre-existing
    # state captured before the run; files written during this run are not
    # "current media"
    currentMediaFiles = out_immediate.get(os.path.abspath(currentOutDir), set())
    ProcessNewFiles(
        curDir,
        files,
        currentMediaFiles,
        inDir,
        outDir,
        compressor,
        progress,
    )

    inputMediaFiles = in_immediate.get(os.path.abspath(currentInDir), set())
    RemoveOldFiles(curDir, inputMediaFiles, currentMediaFiles, outDir)
    RemoveEmptyDirectories(currentOutDir)


def main(
    inDir: str,
    outDir: str,
    inConfigFilePath: str,
    fastestOption,
    batch_size: int = None,
    quality: str = None,
    max_threads: int = None,
):
    if inDir is None:
        print("Source media directory was not provided")
        exit()
    if outDir is None:
        print("Build directory was not provided")
        exit()

    print("Using basisu binary bundled with this install.")

    if not os.path.isdir(inDir):
        print(f"The provided input dir does not exist: {inDir}")
        exit()
    if not os.path.isdir(outDir):
        os.makedirs(outDir)

    # Normalize to absolute paths once so every downstream os.path.join /
    # membership comparison (ProcessNewFiles, RemoveOldFiles, etc.) operates
    # on a consistent absolute form, regardless of whether the caller passed
    # relative paths (the CLI forwards user paths verbatim).
    inDir = os.path.abspath(inDir)
    outDir = os.path.abspath(outDir)

    compress_speed_fastest = False
    if fastestOption:
        compress_speed_fastest = True

    # Build per-directory file indices once with a single os.walk of each tree
    in_immediate, _ = BuildDirectoryIndex(inDir)
    out_immediate, _ = BuildDirectoryIndex(outDir)

    # Resolve sidecars (load/download/generate) before the walk so the routing
    # registry is complete and freshly-written sidecars exist on disk.
    Reset_Registry()
    Resolve_Sidecars(in_immediate)

    print("Processing media files")
    # Indeterminate progress (no total/percentage): tqdm just counts files as
    # they are preprocessed, avoiding an extra full tree walk to pre-count.
    progress = tqdm(unit=" files")
    compressor = TextureCompressor()
    processDir(
        None,
        inDir,
        outDir,
        inConfigFilePath,
        compress_speed_fastest,
        progress,
        in_immediate,
        out_immediate,
        compressor,
    )
    progress.close()

    # All textures collected during the walk are compressed in a single pass
    # here so the progress bar and basisu log cover the whole build at once.
    # batch_size is None unless the caller (e.g. the CLI -batch flag) supplied
    # an explicit value; None lets TextureCompressor pick its cpu-based default.
    compressor.compress(
        outDir,
        compress_speed_fastest,
        batch_size=batch_size,
        quality=quality,
        max_threads=max_threads,
    )

    download_failures = Get_Download_Failure_Count()
    if download_failures > 0:
        print(
            f"Warning: {download_failures} download(s) failed; the corresponding "
            f"media were skipped this run."
        )

    print("Done")


def main_with_args():
    parser = argparse.ArgumentParser(description="Parse command line arguments")

    # Add arguments to the parser
    parser.add_argument(
        "-b", "--builddir", type=str, required=True, help="Path to build directory"
    )
    parser.add_argument(
        "-m", "--mediadir", type=str, required=True, help="Path to media directory"
    )
    parser.add_argument(
        "-d",
        "--depsdir",
        type=str,
        required=False,
        help="Optional path to a dependencies directory containing "
        "BasisUniversal/bin. If omitted, the basisu binary bundled with "
        "this package is used.",
    )
    parser.add_argument("-low", "--fastest", action="store_true")

    # Parse the arguments
    args = parser.parse_args()

    main(args.mediaDir, args.buildDir, args.depsdir, None, args.fastest)


if __name__ == "__main__":
    main_with_args()
