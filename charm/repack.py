from pathlib import Path
import os
from subprocess import call
from time import time

from helpers import get_local_charm


def pack(root: Path, dry_run: bool = False):
    old_cwd = os.getcwd()
    os.chdir(root)
    print('packing charm')
    start = time()
    cmd = 'charmcraft pack'
    if dry_run:
        print(f'would run: {cmd} (in {os.getcwd()})')
    else:
        call(cmd.split(' '))
    print(f'done in {time() - start:4}s')
    os.chdir(old_cwd)


def refresh(root: Path, name: str = None, dry_run: bool = False):
    name = name or '_'.join(root.name.split('_')[:-1])
    print('refreshing charm...')
    cmd = f'juju refresh {name} --path={root.absolute()}'
    if dry_run:
        print(f'would run: {cmd}')
    else:
        call(cmd.split(' '))
    print('done.')


def repack(root: Path = None,
           name: str = None,
           dry_run: bool = False):
    """Packs and refreshes a single charm.
    Based on cwd if no arguments are supplied.
    """
    root = root or get_local_charm()
    pack(root, dry_run=dry_run)
    refresh(root, name=name, dry_run=dry_run)
