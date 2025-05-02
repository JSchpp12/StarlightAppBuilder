import subprocess
import argparse
import json
import os

class TextureInfo:
    def __init__(self, texture_file_path, relative_media_path) -> None:
        self.texture_file_path = texture_file_path
        self.texture_file_name = os.path.basename(texture_file_path)
        self.texture_root_dir = os.path.abspath(os.path.join(self.texture_file_path, os.pardir))
        self.relative_media_path = relative_media_path
        
class TextureCompressor:
    @staticmethod
    def get_filename(full_path: str) -> str:
        """
        Returns the filename without extension from a full path.

        Args:
            full_path (str): The full path to the file.

        Returns:
            str: The filename without extension.
        """
        return os.path.splitext(full_path)[0]
    
    @staticmethod
    def search_for_file(file_name, texture_root_dir):
        file_name_to_find = TextureCompressor.get_filename(file_name)

        for ele in os.listdir(texture_root_dir):
            search_ele = os.path.join(texture_root_dir, ele)
            if os.path.isdir(search_ele):
                deep_search = TextureCompressor.search_for_file(file_name, search_ele)
                if deep_search is not None:
                    return deep_search
            else:
                if file_name_to_find in ele:
                    return search_ele
        
        return None
    
    @staticmethod
    def search_for_star_ignore(texture_file, texture_root_dir) -> None:
        name_to_find = f".star_ignore_{TextureCompressor.get_filename(texture_file)}"
        return TextureCompressor.search_for_file(name_to_find, texture_root_dir)
    
    @staticmethod
    def get_compressed_file_name(texture_info : TextureInfo) -> None: 
        return f"{TextureCompressor.get_filename(texture_info.texture_file_name)}.basis"
    
    @staticmethod
    def should_compress(texture : TextureInfo) -> bool:
        baseName = TextureCompressor.get_filename(os.path.basename(texture.texture_file_name))
        return TextureCompressor.search_for_star_ignore(baseName, texture.texture_root_dir) == None
    
    def __init__(self, basis_u_dir) -> None: 
        self.rel_media_dir_to_textures = {}

        if not os.path.isdir(basis_u_dir):
            raise Exception("Provided directory to basis_u does not exist")
        
        self.basis_u_dir = basis_u_dir

    def add_texture(self, texture : TextureInfo) -> None:
        rel_media_path = os.path.dirname(texture.relative_media_path)

        if rel_media_path not in self.rel_media_dir_to_textures:
            self.rel_media_dir_to_textures[rel_media_path] = []
        self.rel_media_dir_to_textures[rel_media_path].append(texture)

    def compress(self, output_dir) -> None: 
        if not os.path.isdir(output_dir):
            raise Exception("Directory does not exist")
        
        basis_u_exe = os.path.join(self.basis_u_dir, "basisu.exe")

        for rel_output_dir in self.rel_media_dir_to_textures:

            basis_command = [basis_u_exe, "-uastc", "-basis", "-slower", "-individual", "-parallel"]

            for texture in self.rel_media_dir_to_textures[rel_output_dir]:
                relative_src_file_path = os.path.relpath(texture.texture_file_path, start=self.basis_u_dir)
                basis_command.append("-file")
                basis_command.append(relative_src_file_path)
            
            basis_command.append("-output_path")
            basis_command.append(os.path.relpath(os.path.join(output_dir, rel_output_dir), start=self.basis_u_dir))

            try:
                subprocess.run(
                    basis_command,
                    cwd=self.basis_u_dir, 
                    check=True, 
                    text=True
                )
            except subprocess.CalledProcessError as e:
                print("Error occurred")
                print(e)

                raise Exception("Failed to compress textures")