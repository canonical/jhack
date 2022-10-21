import os
import shutil
import stat
from pathlib import Path
from time import sleep

from jhack.helpers import JPopen
from jhack.jinx.cleanup import cleanup
from jhack.jinx.install import jinx_installed, path_to_jinx


def init_jinx(force: bool = False):
    """Initializes the cwd as jinx root. Basically `jinxcraft init`."""
    if not jinx_installed():
        print("run jhack jinx install first.")
        return

    # charmcraft init
    cmd = "charmcraft init"
    if force:
        cmd += " --force"
    proc = JPopen(cmd.split())
    proc.wait()
    while proc.returncode is None:
        sleep(0.1)

    if not proc.returncode == 0:
        print(
            "charmcraft exited with status nonzero. "
            "There is likely to be some output above."
        )
        print("operation aborted.")
        return

    # cleanup metadata files
    cleanup()

    # copy template to src/charm.py
    charm = Path() / "src" / "charm.py"
    shutil.copy(path_to_jinx / "resources" / "template_jinx.py", charm)

    # chmod +x
    st = os.stat(charm)
    os.chmod(charm, st.st_mode | stat.S_IEXEC)

    print("all clear! Happy jinxing.")
