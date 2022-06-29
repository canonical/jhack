This folder holds snap information for jhack.

Build instructions:
    
    cd jhack/snap
    snapcraft --use-lxd

Setup:

    sudo snap set juju=/path/to/juju/executable
    # e.g. /snap/bin/juju
    sudo snap set jujudata=/path/to/juju/ 
    # e.g. /home/chuck/.local/share/juju/
    
