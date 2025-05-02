import json
import os
import sys 
import string
import shutil
import argparse
import filecmp

def GetSubMediaPathFromFullMediaPath(fullMediaPath : string) -> string: 
    return fullMediaPath.split("media\\")[-1]

def CopyFile(source_dir : string, destinationDir : string, file_media_path : string) -> None:
    full_source_path = os.path.join(source_dir, file_media_path)
    full_destination_path = os.path.join(destinationDir, file_media_path)

    if (not os.path.isfile(full_destination_path)):
        shutil.copytree(os.path.abspath(os.path.join(full_source_path, os.pardir)), os.path.abspath(os.path.join(full_destination_path, os.pardir)), dirs_exist_ok=True)

        shutil.copy2(full_source_path, full_destination_path)
    elif(not filecmp.cmp(full_source_path, full_destination_path, shallow=False)):
        shutil.copy2(full_source_path, full_destination_path)

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

def ProcessNewFiles(inputMediaFiles, currentMediaFiles, inputMediaDir, destinationDir) -> None:
    for file in inputMediaFiles:
        CopyFile(inputMediaDir, destinationDir, file)

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
    # Parse the arguments
    args = parser.parse_args()

    inBuildDir = args.builddir
    inMediaDir = args.mediadir

    if inMediaDir is None:
        print("Source media directory was not provided")
        exit()
    if inBuildDir is None:
        print("Build directory was not provided")
        exit()

    destinationMediaDir = os.path.join(inBuildDir, "media")
    destinationConfigFile = os.path.join(inBuildDir, "config.json")
    
    print("Processing media files")
    inputMediaFiles = FindContents(inMediaDir)
    currentMediaFiles = FindContents(destinationMediaDir)
    RemoveOldFiles(inputMediaFiles, currentMediaFiles, destinationMediaDir)
    RemoveEmptyDirectories(destinationMediaDir)
    ProcessNewFiles(inputMediaFiles, currentMediaFiles, os.path.abspath(os.path.join(os.getcwd(), inMediaDir)), destinationMediaDir)
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