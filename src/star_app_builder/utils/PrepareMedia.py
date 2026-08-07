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
        dp_abs = os.path.abspath(dp)
        file_set = set()
        for f in files:
            p = os.path.abspath(os.path.join(dp, f))
            file_set.add(p)
            all_files.add(p)
        immediate[dp_abs] = file_set

    return immediate, all_files


def RemoveOldFiles(subDir, inputMediaFiles, currentMediaFiles, destinationMediaDir):
    """Remove output files that no longer correspond to a current input file.

    Operates per-directory: inputMediaFiles and currentMediaFiles are the
    immediate (non-recursive) absolute-path file sets for the same logical
    subdir. The expected set of output paths is derived from the current
    inputs (input -> output via Create_Media_Path, which honours compression
    renaming and .star_ignore markers), and any existing output file not in
    that expected set is stale and removed.
    """
    expected_outputs = set()
    for in_file in inputMediaFiles:
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
            not Is_File_A_Image(full_src_file)
            and not filecmp.cmp(full_src_file, destination_comparison, shallow=False)
        ) or (
            Is_File_A_Image(full_src_file)
            and not TextureCompressor.should_compress(media_file_path)
            and not filecmp.cmp(full_src_file, destination_comparison, shallow=False)
        ):
            CopyFile(destination_dir, media_file_path)

        progress.update()


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


def main(inDir: str, outDir: str, inConfigFilePath: str, fastestOption, batch_size: int = None, quality: str = None, max_threads: int = None):
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
    compressor.compress(outDir, compress_speed_fastest, batch_size=batch_size, quality=quality, max_threads=max_threads)

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
