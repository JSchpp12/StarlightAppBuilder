import json
import os
import string
import shutil
import argparse
import filecmp

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


def RemoveOldFiles(subDir, inputMediaFiles, currentMediaFiles, destinationMediaDir):
    for file in currentMediaFiles:
        media_path_file = Create_Media_Path(file, subDir)

        if (
            not os.path.join(
                media_path_file.Get_Output_Media_Rel_Path(),
                media_path_file.output_file_base,
            )
            in inputMediaFiles
        ):
            # check if overriden name is in output
            found = False
            media_file = Create_Media_Path(file, subDir)
            for c_out_file in currentMediaFiles:
                if MediaPath(c_out_file, subDir).output_file_base == media_file:
                    found = True
                    break

            if found:
                destinationPath = os.path.join(
                    destinationMediaDir, media_file.Get_Output_Media_Rel_Path()
                )
                os.remove(destinationPath)


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
    deps_path: string,
    use_fastest_encoding: bool,
) -> None:
    compressor = TextureCompressor(os.path.join(deps_path, "BasisUniversal", "bin"))

    for file in input_media_files:
        full_src_file = os.path.abspath(os.path.join(input_media_dir, os.pardir, file))

        media_file_path = Create_Media_Path(full_src_file, subDir)
        destination_comparison = os.path.join(
            destination_dir, media_file_path.output_file_base
        )
        if subDir is not None:
            destination_comparison = os.path.join(
                destination_dir, subDir, media_file_path.output_file_base
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

    compressor.compress(destination_dir, use_fastest_encoding)


def processDir(
    curDir,
    inDir: str,
    outDir: str,
    depsDir: str,
    inConfigFilePath: str,
    fastestOption: bool,
):
    full_deps_dir = os.path.abspath(os.path.join(os.getcwd(), depsDir))

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
                subInDir, inDir, outDir, depsDir, inConfigFilePath, fastestOption
            )
        else:
            #process file
            files.append(elePath)

    currentMediaFiles = FindContents(currentOutDir)
    ProcessNewFiles(
        curDir,
        files,
        currentMediaFiles,
        inDir,
        outDir,
        full_deps_dir,
        fastestOption,
    )


    inputMediaFiles = FindContents(currentInDir)
    RemoveOldFiles(curDir, inputMediaFiles, currentMediaFiles, outDir)
    RemoveEmptyDirectories(currentOutDir)

def main(
    inDir: str,
    outDir: str,
    depsDir: str,
    inConfigFilePath: str,
    fastestOption
):
    if inDir is None:
        print("Source media directory was not provided")
        exit()
    if outDir is None:
        print("Build directory was not provided")
        exit()
    if depsDir is None:
        print(
            "Deps directory was not provided. Ensure proper builds were executed. See init.bat for details."
        )
        exit()

    if not os.path.isdir(inDir):
        print(f"The provided input dir does not exist: {inDir}")
        exit()
    if not os.path.isdir(outDir):
        os.makedirs(outDir)

    compress_speed_fastest = False
    if fastestOption:
        compress_speed_fastest = True

    print("Processing media files")
    processDir(None, inDir, outDir, depsDir, inConfigFilePath, compress_speed_fastest)
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
        required=True,
        help="Path to dependencies directory",
    )
    parser.add_argument("-low", "--fastest", action="store_true")

    # Parse the arguments
    args = parser.parse_args()

    main(args.mediaDir, args.buildDir, args.depsdir, None, args.fastest)


if __name__ == "__main__":
    main_with_args()
