# jhack

This is a homegrown collection of opinionated scripts and utilities to make the 
charm dev's life a somewhat easier.

#### Installation:
##### from sources (dev setup):
Clone the repo; alias '/path/to/jhack/main.py' as 'jhack', or something. 
Ensure the requirements are installed:

    $ pip install -r requirements.txt

##### as package:

    $ python setup.py bdist_wheel
    $ pip install ./dist/jhack-v...whl

##### as snap (coming soon!):
    
    $ sudo snap install --edge --devmode jhack

#### Usage:

    jhack [category] [command]

for example:

    $ jhack utils tail
    $ jhack model rm

Happy hacking!

# utils
## sync

`jhack utils sync ./src application-name/0`

Will watch the ./src folder for changes and push any to application-name/0 
under /charm/src/.

## unbork-juju

`jhack utils unbork-juju`

Does exactly what it says, and it does it pretty well.

## ffwd

`jhack utils ffwd`

Fast-forwards the firing of `update-status` hooks, and restores it to a 'slow' firing rate after the process is killed or after a given timeout.

Self-explanation:
```bash
jhack utils ffwd 
  --timeout 10 # exits after 10 seconds
  --fast-interval 5 # update-status fires each 5 seconds
  --slow-interval 50m # when done, set update-status firing rate to 50 minutes. 
  ```


## tail

Monitors the logs and gathers all logs concerning events being fired on the units.
Will pprint the last N in a nice format. Keeps listening and updates in the 
background as new units are added.

```
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ timestamp ┃ prometheus-k8s/0             ┃ traefik-k8s/0                ┃ prometheus-k8s/1             ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 13:37:15  │                              │                              │ ingress-relation-changed     │
│ 13:37:14  │                              │                              │ ingress-relation-joined      │
│ 13:37:14  │                              │                              │ ingress-relation-changed     │
│ 13:37:13  │                              │                              │ prometheus-peers-relation-c… │
│ 13:37:12  │                              │                              │ prometheus-peers-relation-j… │
│ 13:37:12  │                              │                              │ prometheus-pebble-ready      │
│ 13:37:11  │                              │                              │ start                        │
│ 13:37:10  │                              │                              │ config-changed               │
│ 13:37:09  │ ingress-relation-changed     │                              │                              │
│ 13:37:09  │                              │                              │ database-storage-attached    │
│ 13:37:09  │                              │ ingress-per-unit-relation-c… │                              │
│ 13:37:08  │                              │                              │ leader-settings-changed      │
│ 13:37:08  │                              │ ingress-per-unit-relation-c… │                              │
│ 13:37:08  │ prometheus-peers-relation-c… │                              │                              │
│ 13:37:08  │                              │                              │ ingress-relation-created     │
│ 13:37:07  │                              │ ingress-per-unit-relation-j… │                              │
│ 13:37:07  │ prometheus-peers-relation-j… │                              │                              │
│ 13:37:07  │                              │                              │ prometheus-peers-relation-c… │
│ 13:37:06  │                              │                              │ install                      │
└───────────┴──────────────────────────────┴──────────────────────────────┴──────────────────────────────┘
```


## show-relation 

Displays the databags of units involved in a relation.
if the endpoint is of the form `app-name/id:relation-name`: it will display the application databag and the one for the unit with id=`id`.
If the endpoint is of the form `app-name:relation-name`: it will display the application databag and the databags for all units.
Examples:

`jhack utils show-relation ipu:ingress-per-unit traefik-k8s:ingress-per-unit`

`jhack utils show-relation ipu/0:ingress-per-unit traefik-k8s:ingress-per-unit`

`jhack utils show-relation ipu/0:ingress-per-unit traefik-k8s/2:ingress-per-unit`

Example output:
```bash
                                                      relation data v0.2                                                       
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ category         ┃ traefik-k8s                                         ┃ ipu                                                ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ relation name    │ ingress-per-unit                                    │ ingress-per-unit                                   │
│ interface        │ ingress_per_unit                                    │ ingress_per_unit                                   │
│ leader unit      │ 0                                                   │ 0                                                  │
├──────────────────┼─────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
│ application data │ ╭─────────────────────────────────────────────────╮ │ ╭────────────────────────────────────────────────╮ │
│                  │ │                                                 │ │ │ <empty>                                        │ │
│                  │ │  ingress  ipu/0:                                │ │ ╰────────────────────────────────────────────────╯ │
│                  │ │             url:                                │ │                                                    │
│                  │ │           http://my.it:80/test-charm-ipu-9dg8…  │ │                                                    │
│                  │ │           ipu/1:                                │ │                                                    │
│                  │ │             url:                                │ │                                                    │
│                  │ │           http://my.it:80/test-charm-ipu-9dg8…  │ │                                                    │
│                  │ │           ipu/2:                                │ │                                                    │
│                  │ │             url:                                │ │                                                    │
│                  │ │           http://my.it:80/test-charm-ipu-9dg8…  │ │                                                    │
│                  │ ╰─────────────────────────────────────────────────╯ │                                                    │
│ unit data        │ ╭─ traefik-k8s/0* ─╮ ╭─ traefik-k8s/1 ─╮            │ ╭─ ipu/0*  ────────────────────╮                   │
│                  │ │ <empty>          │ │ <empty>         │            │ │                              │                   │
│                  │ ╰──────────────────╯ ╰─────────────────╯            │ │  host   foo.bar              │                   │
│                  │ ╭─ traefik-k8s/2 ──╮ ╭─ traefik-k8s/3 ─╮            │ │  model  test-charm-ipu-9dg8  │                   │
│                  │ │ <empty>          │ │ <empty>         │            │ │  name   ipu/0                │                   │
│                  │ ╰──────────────────╯ ╰─────────────────╯            │ │  port   80                   │                   │
│                  │                                                     │ ╰──────────────────────────────╯                   │
│                  │                                                     │ ╭─ ipu/1  ─────────────────────╮                   │
│                  │                                                     │ │                              │                   │
│                  │                                                     │ │  host   foo.bar              │                   │
│                  │                                                     │ │  model  test-charm-ipu-9dg8  │                   │
│                  │                                                     │ │  name   ipu/1                │                   │
│                  │                                                     │ │  port   80                   │                   │
│                  │                                                     │ ╰──────────────────────────────╯                   │
│                  │                                                     │ ╭─ ipu/2  ─────────────────────╮                   │
│                  │                                                     │ │                              │                   │
│                  │                                                     │ │  host   foo.bar              │                   │
│                  │                                                     │ │  model  test-charm-ipu-9dg8  │                   │
│                  │                                                     │ │  name   ipu/2                │                   │
│                  │                                                     │ │  port   80                   │                   │
│                  │                                                     │ ╰──────────────────────────────╯                   │
└──────────────────┴─────────────────────────────────────────────────────┴────────────────────────────────────────────────────┘
```

Since v0.3, also peer relations are supported.
Additionally, it supports “show me the nth relation” instead of having to type out the whole app-name:endpoint thing: if you have 3 relations in your model, you can simply do jhack show-relation -n 1 and jhack will print out the 2nd relation from the top (of the same list appearing when you do juju status --relations, that is.

# model
## clear

`jhack model clear`

Will nuke all applications in the current model.


## rm

`jhack model rm`

Will nuke the current model.


# charm

## update
Updates a packed .charm file by dumping into it any number of directories.

`jhack charm update ./my_charm_file-amd64.charm --src ./src --dst src`

This will take ./src and recursively copy it into the packed charm's /src dir 
(it will destroy any existing content).

## sync
Like update, but keeps watching for changes in the provided directories and 
pushes them into the packed charm whenever there's one.

`jhack charm sync ./my_charm_file-amd64.charm --src ./src --dst src`

## repack
Used to pack a charm and refresh it in a juju model. Useful when developing.
If used without arguments, it will assume the cwd is the charm's root, will run 
`charmcraft pack`, and grab the application name from the charm's name.

`jhack charm repack`

Otherwise, you can specify a folder where the packing should be done, and an 
application name to target with the refresh.

`jhack charm repack --root /where/my/charm/root/is --name juju-app-name`


# jinx
Used to play around with [jinx (YAMLess Charms)](https://github.com/PietroPasotti/jinx)

## install

`jhack jinx install`

Downloads the jinx source.

## init

`jhack jinx init`

Basically `jinxcraft init`.
