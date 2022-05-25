import re
from datetime import datetime
from pathlib import Path
from subprocess import call
from typing import Literal

YEARS_PATTERN = "/d/d/d/d-/d/d/d/d"
KNOWN_LICENSES = Literal['apache-long', 'see-lic']

def set_header(template: KNOWN_LICENSES='apache-long',
               years: str = None,
               owner: str = 'Canonical'):
    """Set the header of all source files in the current directory (recursively)
    using a template.
    """
    if not years:
        this_year = datetime.now().year
        years = f"{this_year}-{this_year + 1}"
    else:
        assert re.match(YEARS_PATTERN, years), f'years must match the ' \
                                               f'{YEARS_PATTERN} pattern'

    try:
        import licenseheaders
    except ModuleNotFoundError:
        print('this command requires `licenseheaders` to work. '
              'Run `pip install licenseheaders` and retry.')

    resources_path = Path(__file__).parent / 'resources'
    template_path = resources_path / template
    if not template_path.exists():
        print(
            f'template with name {template!r} not found in {resources_path}')
        return

    print('fixing headers...')
    cmd = f"licenseheaders -t {template_path.absolute()} -y {years} -o {owner}".split()
    call(cmd)

    if template == 'see-lic':
        print('dropping APACHE license copy to ./LICENSE...')
        lic_path = resources_path / "APACHE_LICENSE"
        call(f"cp {lic_path.absolute()} ./LICENSE".split())
