import json
import os
import string
import shutil
import argparse
import filecmp

from TextureEncoder import TextureCompressor
from TextureEncoder import Is_File_A_Image
from TextureEncoder import Create_Media_Path
from PathHelpers import MediaPath

def GetSubMediaPathFromFullMediaPath(fullMediaPath : string) -> string: 
    return fullMediaPath.split("media\\")[-1]

def CopyFile(destination_dir : string, file_path : MediaPath) -> None:
    full_destination_path = os.path.abspath(os.path.join(destination_dir, file_path.Get_Output_Media_Rel_Path()))

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

#copy media as needed 
def FindContents(currentPath : string):
    contents = set()

    for dir in os.listdir(currentPath):
        if "." != dir[0]:
            fullPath = os.path.join(currentPath, dir)
            if os.path.isdir(fullPath):
                #is dir need to go deeper
                deepResults = FindContents(fullPath)
                contents.update(deepResults)
            else:
                contents.add(fullPath)

    return contents

def RemoveOldFiles(inputMediaFiles, currentMediaFiles, destinationMediaDir):
    for file in currentMediaFiles:
        media_path_file = Create_Media_Path(file)

        if not os.path.join(media_path_file.Get_Output_Media_Rel_Path(), media_path_file.output_file_base) in inputMediaFiles:
            #check if overriden name is in output
            found = False
            media_file = Create_Media_Path(file)
            for c_out_file in currentMediaFiles:
                if MediaPath(c_out_file).output_file_base == media_file:
                    found = True
                    break
                
            if found:
                destinationPath = os.path.join(destinationMediaDir, media_file.Get_Output_Media_Rel_Path())
                os.remove(destinationPath)

def RemoveEmptyDirectories(targetDirectory) -> None:
    for dir_path, sub_dir, file_names in os.walk(targetDirectory):
        
        if not sub_dir and not file_names:
                os.rmdir(dir_path)

def ProcessNewFiles(input_media_files, current_media_files, input_media_dir, destination_dir, deps_path : string, use_fastest_encoding : bool) -> None:
    compressor = TextureCompressor(os.path.join(deps_path, "BasisUniversal", "bin"))

    for file in input_media_files:
        full_src_file = os.path.abspath(os.path.join(input_media_dir, os.pardir, file))

        media_file_path = Create_Media_Path(full_src_file)
        destination_comparison =  os.path.join(destination_dir , media_file_path.Get_Output_Media_Rel_Path())

        if destination_comparison not in current_media_files:
            # check if directors need to be created
            destination_dirs = os.path.dirname(os.path.join(destination_dir, media_file_path.Get_Output_Media_Rel_Path()))
            if (not os.path.isdir(destination_dirs)):
                os.makedirs(destination_dirs)

            if Is_File_A_Image(full_src_file) and TextureCompressor.should_compress(media_file_path):
                compressor.add_texture(media_file_path)
            else:
                CopyFile(destination_dir, media_file_path)

    compressor.compress(destination_dir, use_fastest_encoding)

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
    parser.add_argument('-low', '--fastest', action='store_true')

    # Parse the arguments
    args = parser.parse_args()

    inBuildDir = args.builddir
    inMediaDir = args.mediadir
    inDepsDir = args.depsdir

    compress_speed_fastest = False
    if args.fastest:
        compress_speed_fastest = True

    if inMediaDir is None:
        print("Source media directory was not provided")
        exit()
    if inBuildDir is None:
        print("Build directory was not provided")
        exit()
    if inDepsDir is None:
        print("Deps directory was not provided. Ensure proper builds were executed. See init.bat for details.")
        exit()

    destinationMediaDir = os.path.abspath(os.path.join(inBuildDir, "media"))
    if not os.path.isdir(destinationMediaDir):
        os.makedirs(destinationMediaDir)

    destinationConfigFile = os.path.join(inBuildDir, "StarEngine.cfg")
    full_deps_dir = os.path.abspath(os.path.join(os.getcwd(), inDepsDir))
    
    print("Processing media files")
    inputMediaFiles = FindContents(inMediaDir)
    currentMediaFiles = FindContents(destinationMediaDir)
    RemoveOldFiles(inputMediaFiles, currentMediaFiles, destinationMediaDir)
    RemoveEmptyDirectories(destinationMediaDir)
    ProcessNewFiles(inputMediaFiles, currentMediaFiles, os.path.abspath(os.path.join(os.getcwd(), inMediaDir)), destinationMediaDir, full_deps_dir, compress_speed_fastest)
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