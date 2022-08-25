This folder holds snap information for jhack.

Development rebuild oneliner:

    sudo snap remove --purge jhack; snapcraft; sudo snap install --dangerous ./jhack_0.2.92-strict_amd64.snap
    

To publish a new snap version and release on edge:

    snapcraft upload ./jhack_[...].snap --release=edge 

## Setup:
You need to connect jhack to a bunch of plugs for it to work.
This should suffice:

    sudo snap connect jhack:peers microk8s               
    sudo snap connect jhack:juju-client-observe snapd
    sudo snap connect jhack:network snapd
    sudo snap connect jhack:network-bind snapd       
    sudo snap connect jhack:config-lxd snapd          
    sudo snap connect jhack:dot-kubernetes snapd    
    sudo snap connect jhack:dot-local-share-juju snapd

Running `snap connections jhack` should show that there are no unplugged slots.
There is a script to do this quickly if you are developing the local repo.

> sudo bind