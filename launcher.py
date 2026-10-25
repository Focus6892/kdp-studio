"""Entry point of the packaged kdp-studio.exe: with no arguments it opens the web interface, otherwise it behaves like
`python -m kdp_studio <args>` (build, publish, license, doctor ...). Built by build_exe.ps1 with PyInstaller."""

import sys

from kdp_studio.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["ui"]))
