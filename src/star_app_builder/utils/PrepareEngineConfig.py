import os
import json


def createConfigfile(outDir: str, inConfigFilePath: str):
    destinationConfigFile = os.path.join(outDir, "StarEngine.cfg")
    # write config file

    if not os.path.isfile(destinationConfigFile):
        with open(destinationConfigFile, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "app_name": "Default Starlight App",
                    "media_directory": "./media/",
                    "texture_filtering": "linear",
                    "texture_anisotropy": "max",
                    "frames_in_flight": "2",
                    "required_device_feature_geometry_shader": "false",
                    "required_device_feature_shader_float64": "true",
                    "resolution_x": "1280",
                    "resolution_y": "720",
                },
                f,
            )


def main(outDir: str, inConfigFilePath: str):
    if not os.path.isdir(outDir):
        os.mkdir(outDir)

    createConfigfile(outDir, inConfigFilePath)
