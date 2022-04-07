from pathlib import Path
from typing import List, Optional

from charm.update import update as update_charm
from helpers import get_local_charm
from utils.sync import watch


def sync(charm: Path = None,
         src: List[Path] = ('./src', './lib'),
         dst: List[Path] = ('src', 'lib'),
         dry_run: bool = False,
         exts: Optional[str] = None,
         recursive: bool = True,
         polling_interval: float = 1.):
    """Keeps watching some source directories for changes, updating the packed
    charm whenever a change is detected.
    If `charm` is None, it will scan the CWD for the first `*.charm` file
    and use that.
    """
    charm_file = charm or get_local_charm()

    def on_change(files):
        update_charm(charm, src, dst, dry_run)

    watch([charm], on_change,
          exts,
          recursive,
          polling_interval)
