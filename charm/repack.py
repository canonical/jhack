from pathlib import Path
import os
from subprocess import call
from time import time

from charm.utilities import cwd
from helpers import get_local_charm


def pack(root: Path, clean=False, dry_run: bool = False):
    with cwd(root):
        if clean:
            start = time()
            print('cleaning charmcraft project')
            cmd = 'charmcraft clean'
            if dry_run:
                print(f'would run: {cmd} (in {os.getcwd()})')
            else:
                call(cmd.split(' '))
            print(f'done in {time() - start:4}s')

        print('packing charm')
        start = time()
        cmd = 'charmcraft pack'
        if dry_run:
            print(f'would run: {cmd} (in {os.getcwd()})')
        else:
            call(cmd.split(' '))
        print(f'done in {time() - start:4}s')


def refresh(root: Path, charm_name: str = None,
            app_name: str = None, dry_run: bool = False):
    if not charm_name:
        with cwd(root):
            charm_name = get_local_charm()
    else:
        charm_name = Path(charm_name)

    path_to_charm = root / charm_name

    # we guess the app_name from the charm name, assuming it's of the form
    # charm_name_ubuntu-foo-amd64.charm
    app_name = app_name or '_'.join(charm_name.name.split('_')[:-1])
    print(f'refreshing {app_name} --> {charm_name}...')
    cmd = f'juju refresh {app_name} --path={path_to_charm}'
    if dry_run:
        print(f'would run: {cmd}')
    else:
        call(cmd.split(' '))
    print('done.')


def repack(root: Path = None,
           charm_name: str = None,
           clean: bool = False,
           app_name: str = None,
           dry_run: bool = False):
    """Packs and refreshes a single charm.
    Based on cwd if no arguments are supplied.
    """
    root = root or Path(os.getcwd())
    pack(root, dry_run=dry_run, clean=clean)
    refresh(root, app_name=app_name, charm_name=charm_name, dry_run=dry_run)
