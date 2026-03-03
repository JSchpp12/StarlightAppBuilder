import sys
import os
from pathlib import Path
import clang_format
import subprocess
import argparse
import shutil

def format_file(file_path: str, root_dir):
    full_path = os.path.abspath(os.path.join(root_dir, file_path))

    print(file_path)

    result = subprocess.run(["clang-format", f"--style=microsoft", "-i", full_path], 
                        cwd = root_dir,
                        check = True, 
                        capture_output=True, 
                        text=True)

def main():
    parser = argparse.ArgumentParser(description="Format C++ source files using clang-format.")

    parser.add_argument(
        "files",
        help="List of C++ source files to format"
    )
    parser.add_argument(
        "--dir", type=Path,
        help="Directory to recursively format all .cpp/.h/.hpp/.c files"
    )
    parser.add_argument(
        "--style", default="file",
        help="Formatting style (e.g., 'file', 'LLVM', 'Google')"
    )

    args = parser.parse_args()

    files_to_format = args.files.split()

    root_dir = args.dir
    if not os.path.isdir(root_dir):
        print("Path dir does not exist")

    if not files_to_format:
        print("No files to format. Provide files or a directory.")
        return

    for file_path in sorted(files_to_format):
        format_file(file_path, root_dir)

if __name__ == "__main__":
    main()
