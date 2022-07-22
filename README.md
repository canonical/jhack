# jhack

[![jhack](https://snapcraft.io/jhack/badge.svg)](https://snapcraft.io/jhack) [![foo](https://img.shields.io/badge/everything-charming-blueviolet)](https://github.com/PietroPasotti/jhack) [![Awesome](https://cdn.rawgit.com/sindresorhus/awesome/d7305f38d29fed78fa85652e3a63e154dd8e8829/media/badge.svg)](https://discourse.charmhub.io/t/visualizing-relation-databags-for-development-and-debugging/5991)


This is a homegrown collection of opinionated scripts and utilities to make the 
charm dev's life somewhat easier.

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
┏━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ timestamp ┃ traefik-k8s/0                ┃ prometheus-k8s/1             ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 13:37:15  │                              │ ingress-relation-changed     │
│ 13:37:14  │                              │ ingress-relation-joined      │
│ 13:37:14  │                              │ ingress-relation-changed     │
│ 13:37:13  │                              │ prometheus-peers-relation-c… │
│ 13:37:12  │                              │ prometheus-peers-relation-j… │
│ 13:37:12  │                              │ prometheus-pebble-ready      │
│ 13:37:11  │                              │ start                        │
│ 13:37:10  │                              │ config-changed               │
│ 13:37:09  │                              │                              │
│ 13:37:09  │                              │ database-storage-attached    │
│ 13:37:09  │ ingress-per-unit-relation-c… │                              │
│ 13:37:08  │                              │ leader-settings-changed      │
│ 13:37:08  │ ingress-per-unit-relation-c… │                              │
│ 13:37:08  │                              │                              │
│ 13:37:08  │                              │ ingress-relation-created     │
│ 13:37:07  │ ingress-per-unit-relation-j… │                              │
│ 13:37:07  │                              │                              │
│ 13:37:07  │                              │ prometheus-peers-relation-c… │
│ 13:37:06  │                              │ install                      │
└───────────┴──────────────────────────────┴──────────────────────────────┘
```

### There's more!
You can use `tail` to visualize deferrals in `ops`.

If you pass the `-d` flag, short for `--show-defer`, whenever an event is deferred, reemitted, or re-deferred, you'll be able to follow it right along the tail.
You might see then something like:
```text
┏━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ timestamp                ┃ trfk/0                                ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 14:02:53                 │                                     │ │
│ 14:01:36                 │ event_3                           ❯─┘ │
│ 13:56:49                 │ ingress_per_unit_relation_changed     │
│ 13:56:47                 │ ingress_per_unit_relation_changed     │
│ 13:56:47                 │ ingress_per_unit_relation_changed     │
│ 13:56:46                 │ ingress_per_unit_relation_joined      │
│ 13:56:46                 │ event_3                           ❮─┐ │
│ 13:56:46                 │ ingress_per_unit_relation_created   │ │  
│ 13:46:30                 │ event_3                            ⭘┤ │
│ 13:41:51                 │ event_3                           ❯─┘ │
│ 13:41:51                 │ event_2                           ❮─┐ │
│ 13:36:50                 │ event_2                           ❯─┘ │
│ 13:36:50                 │ event_1                           ❮─┐ │
│ 13:31:29                 │ event_1                           ❯─┘ │
                            
                            [...]
```

The little circle is `event-3` getting re-emitted and immediately re-deferred!

The graph can get nice and messy if multiple events get deferred in an interleaved fashion, enabling you to *see* what's going on. Which is nice.

```text
update_status ❮──────┐ 
update_status   .....│ 
update_status  ⭘─────┤ 
update_status   .....│ 
update_status  ⭘─────┤ 
update_status ❮─────┐│ 
update_status ❯─────┼┘ 
update_status  ⭘────┤  
update_status ❮────┐│  
update_status ❯────┼┘  
update_status ❮────┼┐  
update_status  ⭘───┤│  
update_status ❯────┼┘  
update_status  ⭘───┤   
update_status ❮───┐│   
update_status ❮──┐││   
update_status ❯──┼┼┘   
update_status  ⭘─┼┤    
update_status  ⭘─┤│    
update_status ❯──┼┘    
```

And did I mention that there's **colors**?

### You can also `tail` saved logs

Say you have saved two debug-logs with:

```
juju debug-log --date -i prom/0 > prom.log
juju debug-log --date -i trfk/0 > trfk.log
```

Yielding files:

prom.txt
```
unit-prom-0: 2022-07-20 10:00:00 INFO juju.worker.uniter.operation ran "install" hook (via hook dispatching script: dispatch)
unit-prom-0: 2022-07-21 5:00:00 INFO juju.worker.uniter.operation ran "prometheus-peers-relation-created" hook (via hook dispatching script: dispatch)
```

trfk.txt
```
unit-trfk-0: 2022-07-20 11:00:00 INFO juju.worker.uniter.operation ran "start" hook (via hook dispatching script: dispatch)
unit-trfk-0: 2022-07-20 12:00:00 INFO juju.worker.uniter.operation ran "traefik-pebble-ready" hook (via hook dispatching script: dispatch)
```

You can run `jhack utils tail --file=prom.txt --file=trfk.txt` to see the events in all the logs, interlaced in the correct chronological order as expected:

```
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ timestamp      ┃ prom/0                               ┃ trfk/0                  ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━┩
│  5:00:00       │ prometheus_peers_relation_created    │                         │
│ 12:00:00       │                                      │ traefik_pebble_ready    │
│ 11:00:00       │                                      │ start                   │
│ 10:00:00       │ install                              │                         │
├────────────────┼──────────────────────────────────────┼─────────────────────────┤
│ The end.       │ prom/0                               │ trfk/0                  │
├────────────────┼──────────────────────────────────────┼─────────────────────────┤
│ events emitted │ 2                                    │ 2                       │
└────────────────┴──────────────────────────────────────┴─────────────────────────┘
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


## nuke

This utility is the swiss army knife of "just get rid of this thing already".
The broad goal is to have one easy-to-use command to destroy things in the most dirty and unsafe way possible, just **please** _make it fast_ and **please** don't make me type _all those letters_ out.

The tool is designed to be used with `juju status --relations` and `juju models`.

The basic usage is as follows:

`jhack nuke` -> will nuke the current model and that's that.
`jhack nuke foo*` -> will: 
 - scan `juju models` for models whose **name begins with "foo"** and nuke each one of them.
 - For each model it did **not** target as nukeable in the previous step, it will scan `juju status -m that-model` and:
   - for each app whose name begins with "foo", it will nuke it.
   - for each relation NOT involving an app selected for nukage in the previous step, if either the provider or requirer starts with "foo", it will nuke it. 

You can switch between "starts with" / "ends with" and "contains" matching modes by placing stars around the string:

 - `jhack nuke foo`  --> same as `jhack nuke foo*`
 - `jhack nuke *foo`  --> same algorithm as above, but will nuke stuff whose name _ends with_ "foo".
 - `jhack nuke *foo*`  --> ... will nuke stuff that _contains_ "foo"
 - `jhack nuke !foo`  --> _exact match_ only. So it will presumably only nuke one thing, except if you have many models with identically-named apps or relations in them. Then they'll all be vanquished.

For targeting relations only, you can type out the endpoint name up to and including the colon. For example, for purging all relations involving your `my-db` application,
you could do:
`jhack nuke "my-db:"`, that will match all the relations of your app. They're history now.

### Safety tips

 - Learn to use the command by trying out the `--dry-run` flag first, that will print out what it would nuke without actually nuking anything. 
 - The command has an optional `-n` flag that allows you to specify the expected number of nukes that should be fired out. If more or less than `n` nukeables are matched, the command will print an error message and abort.


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
