from os import mkdir
from pathlib import Path
from subprocess import call
from tempfile import tempdir, mkdtemp

from charm.utilities import cwd


def init(name: str,
         template: str = 'k8s',
         source_repo: str = 'https://github.com/PietroPasotti/operator-templates.git'):
    """Clones the specified template in a subdirectory of the specified name.
    """
    name = Path(name).absolute()
    if name.exists():
        if name.is_dir() and set(name.glob('*')):
            print(f'a directory called {name!r} exists and is not empty: '
                  f'please specify a new name for the charm')
            return
        elif not name.is_dir():
            print(f'a file called {name!r} is present.')
            return
    else:
        mkdir(name)

    temp_dir = mkdtemp()

    with cwd(temp_dir):
        print(f'fetching {source_repo}...')
        call(f'git clone -b master --depth 1 --single-branch {source_repo}'.split())

        print(f'copying template {template!r}...')
        call(f'cp -r ./operator-templates/{template} {name}'.split())
