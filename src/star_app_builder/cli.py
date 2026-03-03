import os
import argparse

from star_app_builder.utils import mainPrepMedia, mainPrepConfig


def addMediaPrepArgs(subparser):
    parserGenerate = subparser.add_parser("prep-media")

    parserGenerate.add_argument(
        "-out", "--outDir", help="Directory where results will be placed"
    )
    parserGenerate.add_argument(
        "-in", "--inDir", help="Directory containing files to be processed"
    )
    parserGenerate.add_argument(
        "-deps",
        "--depsDir",
        help="Directory containing the dependencies for media prep such as basis universal",
    )
    parserGenerate.add_argument(
        "-low", "--fastest", action="store_true", help="Enable low quality mode"
    )
    parserGenerate.add_argument(
        "-config",
        "--createConfig",
        action="store_true",
        help="Trigger create config file",
    )


def addConfigPrepArgs(subparser):
    parserGenerate = subparser.add_parser("create-config")

    parserGenerate.add_argument(
        "-out", "--outDir", help="Directory where config file will be placed"
    )
    parserGenerate.add_argument(
        "-in", "--inConfig", help="Template config file to copy to output"
    )


def main():
    parser = argparse.ArgumentParser(
        prog="StarlightAppBuilder",
        description="Entrypoint for utils provided to build starlight applications",
    )

    subparser = parser.add_subparsers(dest="command")

    addMediaPrepArgs(subparser)
    addConfigPrepArgs(subparser)

    args = parser.parse_args()

    if args.command == "prep-media":
        mainPrepMedia(args.inDir, args.outDir, args.depsDir, None, args.fastest, args.createConfig)
    if args.command == "create-config":
        mainPrepConfig(args.outDir, args.inConfig)
    else:
        print("Invalid argument")
        exit()
