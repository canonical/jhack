from pathlib import Path
from typing import Union, AnyStr, List


class FilePeeker:
    """A wrapper around a file object that allows you to peek ahead in the file

    To interact with the base file object, use the .file attribute
    """
    # TODO: Add enter and exit to make cleanup easier
    def __init__(self, filename: Union[str, Path]):
        self.filename = str(filename)
        self.file = open(self.filename, "r")

    def peekline(self) -> AnyStr:
        """Peek at the next line of the file without moving the file pointer."""
        return self.peeklines(n_lines=1)[0]

    def peeklines(self, n_lines: int) -> List[AnyStr]:
        """Peek at the next n_lines of the file without moving the file pointer.

        Inspired by: https://stackoverflow.com/a/16840747/5394584
        """
        original_position = self.file.tell()
        lines = [self.file.readline() for _ in range(n_lines)]
        self.file.seek(original_position)
        return lines

    def read(self, *args, **kwargs):
        """Convenience alias to access underlying file object's read method"""
        return self.file.read(*args, **kwargs)

    def readline(self, *args, **kwargs):
        """Convenience alias to access underlying file object's read method"""
        return self.file.readline(*args, **kwargs)

    def readlines(self, *args, **kwargs):
        """Convenience alias to access underlying file object's readlines method"""
        return self.file.readlines(*args, **kwargs)

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

