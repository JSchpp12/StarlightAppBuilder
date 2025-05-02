import subprocess
import argparse
import json
import os

class TextureCompressionSettings:
    def __init__(self) -> None:
        pass

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

    def __init__(self, texture_file_path, basis_u_dir) -> None: 
        self.texture_file_path = texture_file_path
        self.texture_file_name = os.path.basename(texture_file_path)

        if not os.path.isdir(basis_u_dir):
            raise Exception("Provided directory to basis_u does not exist")
        
        self.basis_u_dir = basis_u_dir
        self.texture_root_dir = os.path.abspath(os.path.join(self.texture_file_path, os.pardir))

    def get_compressed_file_name(self) -> None: 
        return f"{TextureCompressor.get_filename(self.texture_file_name)}.basis"
    
    def should_compress(self) -> bool:
        baseName = TextureCompressor.get_filename(os.path.basename(self.texture_file_name))
        return TextureCompressor.search_for_star_ignore(baseName, self.texture_root_dir) == None

    def compress(self, output_dir) -> None: 
        if not os.path.isdir(output_dir):
            raise Exception("Directory does not exist")
        
        compressed_file_name = self.get_compressed_file_name()
        file_output = os.path.join(output_dir, f"{compressed_file_name}")
        relative_src_file_path = os.path.relpath(self.texture_file_path, start=output_dir)
        basis_u_exe = os.path.join(self.basis_u_dir, "basisu.exe")

        subprocess.run(
            # ["basisu", "uastc", f"{relative_src_file_path}"], 
            [basis_u_exe, "-uastc", "-basis", "-slower", relative_src_file_path],
            cwd=output_dir, 
            check=True, 
            text=True
        )