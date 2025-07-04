import subprocess
import argparse
import json
import os

from PathHelpers import MediaPath
from PIL import Image
        
class TextureCompressor:
    @staticmethod
    def search_for_file(file_path : str, texture_root_dir):
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
    def search_for_star_ignore(texture_path : MediaPath) -> None:
        name_to_find = f".star_ignore_{texture_path.Get_Output_Stem()}"
        return TextureCompressor.search_for_file(name_to_find, os.path.dirname(texture_path.full_input_path))
    
    @staticmethod
    def get_compressed_file_name(texture_info : MediaPath, use_basis_file_format : bool = False) -> str: 
        if use_basis_file_format:
            return texture_info.Get_Output_Stem() + ".basis"
        else:
            return texture_info.Get_Output_Stem() + ".ktx2"
    
    @staticmethod
    def should_compress(texture : MediaPath) -> bool:
        return TextureCompressor.search_for_star_ignore(texture) == None
    
    @staticmethod
    def batch_list(lst, batch_size):
        """Split list into batches of specified size."""
        for i in range(0, len(lst), batch_size):
            yield lst[i:i + batch_size]

    
    def __init__(self, basis_u_dir : str, use_basis_file_type : bool = False) -> None: 
        self.rel_media_dir_to_textures = {}
        self.use_bases_file_type = use_basis_file_type

        if not os.path.isdir(basis_u_dir):
            raise Exception("Provided directory to basis_u does not exist")
        
        self.basis_u_dir = basis_u_dir

    def add_texture(self, texture : MediaPath) -> None:
        if texture.relative_media_path_parent not in self.rel_media_dir_to_textures:
            self.rel_media_dir_to_textures[texture.relative_media_path_parent] = []
        self.rel_media_dir_to_textures[texture.relative_media_path_parent].append(texture)

    def compress(self, output_dir, use_compress_speed_fastest: bool, batch_size: int = 50) -> None:
        if not os.path.isdir(output_dir):
            os.mkdir(output_dir)
        
        basis_u_exe = os.path.join(self.basis_u_dir, "basisu.exe")
        if not os.path.isfile(basis_u_exe):
            basis_u_exe = os.path.join(self.basis_u_dir, "basisu")

        for rel_output_dir, textures in self.rel_media_dir_to_textures.items():
            base_command = [basis_u_exe, "-uastc", "-individual", "-parallel", "-mipmap"]

            if self.use_bases_file_type:
                base_command.append("-basis")

            base_command.append("-fastest" if use_compress_speed_fastest else "-slower")

            full_output = os.path.join(output_dir, rel_output_dir)
            os.makedirs(full_output, exist_ok=True)

            base_command += ["-output_path", os.path.abspath(full_output)]

            # Batch texture files
            texture_paths = [t.full_input_path for t in textures]
            for batch in TextureCompressor.batch_list(texture_paths, batch_size):
                batch_command = base_command.copy()
                for texture_path in batch:
                    batch_command += ["-file", texture_path]

                try:
                    subprocess.run(
                        batch_command,
                        cwd=self.basis_u_dir,
                        check=True,
                        text=True
                    )
                except subprocess.CalledProcessError as e:
                    print("Error occurred during texture compression:")
                    print(e)
                    raise Exception("Failed to compress textures")
            
def Is_File_A_Image(media_file : str) -> bool:
    if ".basis" in media_file:
        return True
    
    try:
        with Image.open(media_file) as img:
            img.verify()
            return True
    except Exception as ex:
        if ".png" in media_file or ".jpg" in media_file:
            return True
        
        return False
    
    return False

def Generate_Media_File_For_Image(media_file : str) -> MediaPath:
    media_file_path = MediaPath(media_file)

    if (TextureCompressor.should_compress(media_file_path)):
        media_file_path.output_file_base = TextureCompressor.get_compressed_file_name(media_file_path)
    return media_file_path

def Create_Media_Path(full_media_path : str) -> MediaPath:
    if (Is_File_A_Image(full_media_path)):
        return Generate_Media_File_For_Image(full_media_path)
    else:
        return MediaPath(full_media_path)