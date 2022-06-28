import contextlib
import os
import shutil
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from charm.update import update

dnttchme = 'don_t_touch_me.txt'
untouched = 'untouched'


def update_charm(*args, **kwargs):
    with patch('charm.update.chmod_plusx', wraps=lambda file: None):
        yield update(*args, **kwargs)


@pytest.fixture
def charm(tmp_path_factory):
    charm = tmp_path_factory.mktemp('charm')
    charm_src = charm / 'src'
    charm_lib = charm / 'lib'
    untouchable = charm / dnttchme
    untouchable.touch()  # lol
    untouchable.write_text(untouched)

    charm_src.mkdir()
    charm_lib.mkdir()
    (charm_src / 'charm.py').write_text('charm')
    (charm_lib / 'libfile.py').write_text('libfile')

    # {charm}
    #  - src
    #     - charm.py
    #  - lib
    #     - libfile.py

    return charm


@pytest.fixture
def packed_charm(charm, tmp_path):
    return Path(shutil.make_archive(str(tmp_path), 'zip', charm))


@pytest.fixture
def mock_baz(tmp_path_factory):
    baz_dir = tmp_path_factory.mktemp('baz_dir')
    (baz_dir / 'baz_file.py').write_text('BAZ')
    return baz_dir


def check_base(baz_content, packed_charm):
    zf = zipfile.ZipFile(packed_charm)
    assert len(zf.filelist) == 7
    charm_file = zf.open('src/charm.py').read().decode('utf-8').strip()
    assert charm_file == 'charm'  # unchanged
    lib_file = zf.open('lib/libfile.py').read().decode('utf-8').strip()
    assert lib_file == 'libfile'  # unchanged
    untouched_zf = zf.open(dnttchme).read().decode('utf-8').strip()
    assert untouched_zf == untouched

    baz_file = zf.open('baz/baz_file.py').read().decode('utf-8').strip()
    assert baz_file == baz_content


def test_charm_update(tmp_path_factory, packed_charm, mock_baz):
    assert packed_charm.exists()
    update_charm(packed_charm, [mock_baz], ['baz'])

    check_base('BAZ', packed_charm)

    # now let's touch baz
    change = 'BAZ IS THE NEW FOO'
    (mock_baz / 'baz_file.py').write_text(change)

    update_charm(packed_charm, [mock_baz], ['baz'])
    check_base(change, packed_charm)


@contextlib.contextmanager
def cwd(wd):
    old_wd = os.getcwd()
    os.chdir(wd)
    yield
    os.chdir(old_wd)


@pytest.fixture
def mock_charm_dev_dir(tmp_path_factory):
    return tmp_path_factory.mktemp('charm_dev_dir')


def test_charm_update_default(packed_charm, mock_charm_dev_dir):
    (mock_charm_dev_dir / 'src').mkdir()
    (mock_charm_dev_dir / 'lib').mkdir()
    (mock_charm_dev_dir / 'src' / 'charm.py').write_text('FOO')
    (mock_charm_dev_dir / 'lib' / 'libfile.py').write_text('BAR')

    with cwd(mock_charm_dev_dir):
        update_charm(packed_charm)

    zf = zipfile.ZipFile(packed_charm)
    assert len(zf.filelist) == 5
    charm_file = zf.open('src/charm.py').read().decode('utf-8').strip()
    assert charm_file == 'FOO'
    lib_file = zf.open('lib/libfile.py').read().decode('utf-8').strip()
    assert lib_file == 'BAR'

    untouched_zf = zf.open(dnttchme).read().decode('utf-8').strip()
    assert untouched_zf == untouched
