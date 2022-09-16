from pathlib import Path
from typing import List, Union

import parse

from jhack.utils.file_peeker import FilePeeker


class DebugLogInterlacer:
    """Helper to interlace debug-logs

    Yields the chronologically next row across one or more debug log files, keeping track of
    progress so that successive calls to readline will progress through the monitored files.
    """

    line_pattern = parse.compile("{_}: {timestamp:ti} {_}")
    line_pattern_no_date = parse.compile("{_}: {timestamp:tt} {_}")

    def __init__(self, files: List[Union[Path, str]]):
        self.files = [Path(f) for f in files]
        self.file_peekers = [FilePeeker(f) for f in self.files]

    def readline(self):
        """Returns the chronologically next line from the collection log files"""
        next_line_timestamp = None
        next_line_file_index = None

        if len(self.files) == 1:
            fp = self.file_peekers[0]
            return fp.readline()

        for i, file_peeker in enumerate(self.file_peekers):
            try:
                line = file_peeker.peekline()

                # Skip blank lines
                if line.strip() == "":
                    continue

                if match := self.line_pattern.parse(line):
                    this_timestamp = match.named["timestamp"]
                    if (
                        next_line_timestamp is None
                        or this_timestamp < next_line_timestamp
                    ):
                        next_line_timestamp = this_timestamp
                        next_line_file_index = i
                else:
                    if self.line_pattern_no_date.parse(line):
                        raise ValueError(
                            f"Could not parse line from file {file_peeker.filename}, no full "
                            f"datetime found.  Did you export with `juju debug-log --date`?"
                        )
                    else:
                        raise ValueError(
                            f"Cannot parse line {line} from file {file_peeker.filename} for "
                            f"unknown reasons."
                        )
            except StopIteration:
                continue

        if next_line_file_index is not None:
            return self.file_peekers[next_line_file_index].readline()
        else:
            return ""
