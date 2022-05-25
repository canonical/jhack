import os
import re
import sys
from datetime import datetime
from pathlib import Path
from subprocess import call

YEARS_PATTERN = "/d/d/d/d-/d/d/d/d"
KNOWN_LICENSES = {'apache-long', 'apache-short'}


def lic(template: str = 'apache-short',
        years: str = None,
        owner: str = 'Canonical'):
    """Set the header of all source files in the current directory (recursively)
    using one of the following templates {}.
    """.format(KNOWN_LICENSES)

    if template not in KNOWN_LICENSES:
        print(f'not a known license: {template}. Try one of {KNOWN_LICENSES}.')

    if not years:
        this_year = datetime.now().year
        years = f"{this_year}-{this_year + 1}"
    else:
        assert re.match(YEARS_PATTERN, years), f'years must match the ' \
                                               f'{YEARS_PATTERN} pattern'

    try:
        import licenseheaders
        try:
            # python 3.4+ should use builtin unittest.mock not mock package
            from unittest.mock import patch
        except ImportError:
            from mock import patch

    except ModuleNotFoundError:
        print('this command requires `licenseheaders` and `mock` to work. '
              'Run `pip install licenseheaders mock` and retry.')
        return

    resources_path = Path(__file__).parent / 'resources'
    template_path = resources_path / template
    if not template_path.exists():
        print(
            f'template with name {template!r} not found in {resources_path}')
        return

    print('fixing headers...')
    cmd = f"licenseheaders -t {template_path.absolute()} -y {years} " \
          f"-o {owner}".split()

    with patch.object(sys, 'argv', cmd):
        # licenseheaders was not meant to be used from other scripts, this is
        # easier than spawning a child process from the same interpreter...
        licenseheaders.main()

    if template == 'apache-short':
        print('dropping APACHE license copy to ./LICENSE...')
        lic_path = resources_path / "APACHE_LICENSE"
        call(f"cp {lic_path.absolute()} ./LICENSE".split())
