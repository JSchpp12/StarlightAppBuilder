import json
import os
import string
import shutil
import argparse
import filecmp

from PIL import Image

from TextureEncoder import TextureInfo
from TextureEncoder import TextureCompressor

def GetSubMediaPathFromFullMediaPath(fullMediaPath : string) -> string: 
    return fullMediaPath.split("media\\")[-1]

def CopyFile(source_dir : string, destination_dir : string, file_media_path : string) -> None:
    full_source_path = os.path.join(source_dir, file_media_path)
    full_destination_path = os.path.join(destination_dir, file_media_path)

    if (not os.path.isfile(full_destination_path)):
        shutil.copytree(os.path.abspath(os.path.join(full_source_path, os.pardir)), os.path.abspath(os.path.join(full_destination_path, os.pardir)), dirs_exist_ok=True)

        shutil.copy2(full_source_path, full_destination_path)
    elif(not filecmp.cmp(full_source_path, full_destination_path, shallow=False)):
        shutil.copy2(full_source_path, full_destination_path)

def CheckForFileInDirectory(file_to_find, search_directory) -> bool:
    for ele in os.listdir(search_directory):
        if file_to_find in ele:
            return True
    return False

#copy media as needed 
def FindContents(currentPath : string):
    contents = set()

    for dir in os.listdir(currentPath):
        if ".star_ignore" not in dir:
            fullPath = os.path.join(currentPath, dir)
            if os.path.isdir(fullPath):
                #is dir need to go deeper
                deepResults = FindContents(fullPath)
                contents.update(deepResults)
            else:
                focusedPath = GetSubMediaPathFromFullMediaPath(fullPath)
                contents.add(focusedPath)

    return contents

def RemoveOldFiles(inputMediaFiles, currentMediaFiles, destinationMediaDir):
    for file in currentMediaFiles:
        if not file in inputMediaFiles:
            destinationPath = os.path.join(destinationMediaDir, file)
            os.remove(destinationPath)

def RemoveEmptyDirectories(targetDirectory) -> None:
    for dir_path, sub_dir, file_names in os.walk(targetDirectory):
        
        if not sub_dir and not file_names:
                os.rmdir(dir_path)

def IsFileAImage(media_file : str) -> bool:
    if ".basis" in media_file:
        return True
    
    try:
        with Image.open(media_file) as img:
            img.verify()
            return True
    except:
        return False
    
    return False

def ProcessNewFiles(input_media_files, current_media_files, input_media_dir, destination_dir, deps_path : string) -> None:
    compressor = TextureCompressor(os.path.join(deps_path, "BasisUniversal", "bin"))

    for file in input_media_files:
        full_src_file = os.path.abspath(os.path.join(input_media_dir, file))
        if IsFileAImage(full_src_file):
            textureCompressRequest = TextureInfo(full_src_file, file)

            if (TextureCompressor.should_compress(textureCompressRequest)):
                compressedName = TextureCompressor.get_compressed_file_name(textureCompressRequest)
                relCompressedName = os.path.join(textureCompressRequest.texture_root_dir, compressedName)
                if not relCompressedName in current_media_files:
                    compressor.add_texture(textureCompressRequest)
            else:
                CopyFile(input_media_dir, destination_dir, file)
        elif file not in current_media_files:
            CopyFile(input_media_dir, destination_dir, file)

    compressor.compress(destination_dir)

if __name__ == "__main__":
    inBuildDir = None
    inMediaDir = None
    inConfigFilePath = None

    parser = argparse.ArgumentParser(description='Parse command line arguments')

    # Add arguments to the parser
    parser.add_argument('-b', '--builddir', type=str, required=True,
                        help='Path to build directory')
    parser.add_argument('-m', '--mediadir', type=str, required=True,
                        help='Path to media directory')
    parser.add_argument('-d', '--depsdir', type=str, required=True, 
                        help="Path to dependencies directory")

    # Parse the arguments
    args = parser.parse_args()

    inBuildDir = args.builddir
    inMediaDir = args.mediadir
    inDepsDir = args.depsdir

    if inMediaDir is None:
        print("Source media directory was not provided")
        exit()
    if inBuildDir is None:
        print("Build directory was not provided")
        exit()
    if inDepsDir is None:
        print("Deps directory was not provided. Ensure proper builds were executed. See init.bat for details.")
        exit()

    destinationMediaDir = os.path.join(inBuildDir, "media")
    if not os.path.isdir(destinationMediaDir):
        os.mkdir(destinationMediaDir)
    destinationConfigFile = os.path.join(inBuildDir, "config.json")
    full_deps_dir = os.path.abspath(os.path.join(os.getcwd(), inDepsDir))
    
    print("Processing media files")
    inputMediaFiles = FindContents(inMediaDir)
    currentMediaFiles = FindContents(destinationMediaDir)
    RemoveOldFiles(inputMediaFiles, currentMediaFiles, destinationMediaDir)
    RemoveEmptyDirectories(destinationMediaDir)
    ProcessNewFiles(inputMediaFiles, currentMediaFiles, os.path.abspath(os.path.join(os.getcwd(), inMediaDir)), destinationMediaDir, full_deps_dir)
    print("Done")

    #write config file
    if not os.path.isfile(destinationConfigFile):
        with open(destinationConfigFile, 'w', encoding='utf-8') as f:
            json.dump({
                'app_name': 'Default Starlight App',
                'media_directory': './media/',
                'texture_filtering': 'linear',
                'texture_anisotropy': 'max' ,
                'frames_in_flight': '2', 
                'required_device_feature_geometry_shader' : 'false',
                'required_device_feature_shader_float64': 'true',
                'resolution_x' : '1280', 
                'resolution_y' : '720'
            }, f)