import shutil
import zipfile
from pathlib import Path

import pytest
import jhack


def test_charm_update(tmp_path_factory, tmp_path):
    charm = tmp_path_factory.mktemp('charm')
    charm_src = charm / 'src'
    charm_lib = charm / 'lib'
    dnttchme = 'don_t_touch_me.txt'
    untouchable = charm / dnttchme
    untouchable.touch()  # lol
    untouched = 'untouched'
    untouchable.write_text(untouched)

    charm_src.mkdir()
    charm_lib.mkdir()
    (charm_src / 'charm.py').touch()
    (charm_lib / 'libfile.py').touch()

    # {charm}
    #  - src
    #     - charm.py
    #  - lib
    #     - libfile.py

    packed_charm_path = Path(shutil.make_archive(str(tmp_path), 'zip', charm))

    src_dir = tmp_path_factory.mktemp('src')
    lib_dir = tmp_path_factory.mktemp('lib')
    foo = 'FOO'
    (src_dir / 'charm.py').write_text(foo)
    bar = 'BAR'
    (lib_dir / 'libfile.py').write_text(bar)

    assert packed_charm_path.exists()
    jhack.update_charm(packed_charm_path, [src_dir, lib_dir])

    zf = zipfile.ZipFile(packed_charm_path)
    assert len(zf.filelist) == 5
    charm_file = zf.open('src/charm.py').read().decode('utf-8')
    assert charm_file.strip() == foo
    lib_file = zf.open('lib/libfile.py').read().decode('utf-8')
    assert lib_file.strip() == bar

    untouched_zf = zf.open(dnttchme).read().decode('utf-8')
    assert untouched_zf.strip() == untouched
