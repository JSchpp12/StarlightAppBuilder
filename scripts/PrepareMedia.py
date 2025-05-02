import json
import os
import sys 
import string
import shutil
import argparse
import filecmp

from PIL import Image

from TextureEncoder import TextureCompressor

def FindBasisUniversal(search_path) -> string:

    pass

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

def PrepareImage(source_dir : string, destination_root_dir : string, file_media_path : string, basis_u_dir : string) -> None:
    compressor = TextureCompressor(os.path.abspath(os.path.join(source_dir, file_media_path)), os.path.join(basis_u_dir, "BasisUniversal", "bin"))

    result_name = compressor.get_compressed_file_name()
    result_dir = os.path.abspath(os.path.join(destination_root_dir, file_media_path, os.pardir))
    
    if not CheckForFileInDirectory(result_name, result_dir) and compressor.should_compress():
        compressor.compress(result_dir)

#copy media as needed 
def FindContents(currentPath : string):
    contents = set()

    for dir in os.listdir(currentPath):
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
    try:
        with Image.open(media_file) as img:
            img.verify()
            return True
    except:
        return False
    
    return False

def ProcessNewFiles(input_media_files, current_media_files, input_media_dir, destination_dir, deps_path : string) -> None:
    for file in input_media_files:
        full_src_file = os.path.abspath(os.path.join(input_media_dir, file))
        if IsFileAImage(full_src_file):
            PrepareImage(input_media_dir, destination_dir, file, deps_path)
        elif file not in current_media_files:
            CopyFile(input_media_dir, destination_dir, file)

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
        print("Deps directory was not provided")
        exit()

    destinationMediaDir = os.path.join(inBuildDir, "media")
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