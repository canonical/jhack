import os
from pathlib import Path


def cleanup():
    """Remove standard metadata yaml files."""
    print("cleaning up metadata files...")
    to_remove = ["charmcraft", "actions", "metadata", "config"]
    for file in to_remove:
        os.remove(Path() / (file + ".yaml"))
