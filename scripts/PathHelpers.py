import os

class MediaPath:
    @staticmethod
    def GetSubMediaPathFromFullMediaPath(fullMediaPath : str) -> str: 
        return fullMediaPath.split("media\\")[-1]
    
    @staticmethod
    def GetStemOfFile(full_path : str) -> str:
        base = os.path.basename(full_path)
        return os.path.splitext(base)[0]
    
    def __init__(self, full_path : str, override_output_file : str = None) -> None:
        self.full_input_path = full_path
        self.relative_media_path_parent = os.path.dirname(MediaPath.GetSubMediaPathFromFullMediaPath(full_path))
        self.input_file_base = os.path.basename(full_path)

        if override_output_file is None:
            self.output_file_base = os.path.basename(full_path)
        else:
            self.output_file_base = override_output_file

    def Get_Input_Stem(self) -> str:
        return os.path.splitext(self.input_file)[0]
    
    def Get_Output_Stem(self) -> str:
        return os.path.splitext(self.output_file_base)[0]
    
    def Get_Output_Media_Rel_Path(self) -> str:
        return os.path.join(self.relative_media_path_parent, self.output_file_base)