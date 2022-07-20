from contextlib import nullcontext

import pytest
from _pytest.python_api import RaisesContext  # Not sure if there's a better way for this
from jhack.utils.debug_log_interlacer import DebugLogInterlacer


@pytest.mark.parametrize(
    'input_files, expected_output_file, context_raised',
    (
            (
                    ["./tail_mocks/interlace-log-0.txt"],
                    "./tail_mocks/interlace-log-0.txt",
                    nullcontext(),
            ),
            (
                    ["./tail_mocks/interlace-log-0.txt", "./tail_mocks/interlace-log-1.txt"],
                    "./tail_mocks/interlace-log-combined.txt",
                    nullcontext(),
            ),
            (
                    ["./tail_mocks/interlace-log-no-date.txt", "./tail_mocks/interlace-log-1.txt"],
                    None,
                    pytest.raises(ValueError),
            ),
    ),
)
def test_debug_file_interlace_read(input_files, expected_output_file, context_raised):

    dli = DebugLogInterlacer(input_files)

    lines = []
    with context_raised:
        while True:
            this_line = dli.readline()
            if this_line:
                lines.append(this_line)
            else:
                break

    if not isinstance(context_raised, RaisesContext):
        # If we didn't raise, then assert the output is correct
        with open(expected_output_file, 'r') as fin:
            expected_lines = fin.readlines()

        assert lines == expected_lines

