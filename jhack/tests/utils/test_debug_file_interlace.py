import pytest
from jhack.utils.debug_log_interlacer import DebugLogInterlacer


@pytest.mark.parametrize(
    'input_files, expected_output_file',
    (
            (
                    ["./tail_mocks/interlace-log-0.txt"],
                    "./tail_mocks/interlace-log-0.txt",
            ),
            (
                    ["./tail_mocks/interlace-log-0.txt", "./tail_mocks/interlace-log-1.txt"],
                    "./tail_mocks/interlace-log-combined.txt",
            ),
            (
                    ["./tail_mocks/interlace-log-no-date.txt",
                     "./tail_mocks/interlace-log-1.txt"],
                    None,
            ),
    ),
)
def test_debug_file_interlace_read(input_files, expected_output_file):

    dli = DebugLogInterlacer(input_files)

    lines = []

    def read_all():
        while True:
            this_line = dli.readline()
            if this_line:
                lines.append(this_line)
            else:
                break

    if not expected_output_file:
        with pytest.raises(ValueError):
            read_all()
    else:
        read_all()

    if expected_output_file is not None:
        # If we didn't raise, then assert the output is correct
        with open(expected_output_file, 'r') as fin:
            expected_lines = fin.readlines()

        assert lines == expected_lines

