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
        "-low", "--fastest", action="store_true", help="Enable low quality mode"
    )
    parserGenerate.add_argument(
        "-config",
        "--createConfig",
        action="store_true",
        help="Trigger create config file",
    )
    parserGenerate.add_argument(
        "-batch",
        "--batchSize",
        type=int,
        default=None,
        help="Number of textures handed to basisu per batch. Defaults to "
        "4x the CPU count. Lower this (e.g. 20) when very large textures "
        "cause a batch to hang with low CPU usage.",
    )
    parserGenerate.add_argument(
        "-q",
        "--quality",
        choices=["lossless", "high", "medium", "low"],
        default=None,
        help="Compression quality preset: lossless (100), high (90), medium "
        "(75), or low (50). If omitted, quality defaults to 100, or 25 when "
        "-low/--fastest is set. An explicit -q value takes precedence over "
        "--fastest.",
    )
    parserGenerate.add_argument(
        "-mt",
        "--maxThreads",
        type=int,
        default=None,
        help="Cap the number of threads basisu's -parallel uses per batch "
        "(maps to basisu -max_threads). Default is the full hardware thread "
        "count. Lower this (e.g. half your cores) when very large UASTC "
        "textures cause high memory use or swapping, since -parallel keeps "
        "one image resident per thread.",
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
        mainPrepMedia(
            args.inDir, args.outDir, None, args.fastest, args.batchSize, args.quality, args.maxThreads
        )
    elif args.command == "create-config":
        mainPrepConfig(args.outDir, args.inConfig)
    else:
        print("Invalid argument")
        exit()
