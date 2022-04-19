# utils
## sync

`jhack utils sync ./src application-name/0`

Will watch the ./src folder for changes and push any to application-name/0 
under /charm/src/.

## unbork-juju

`jhack utils unbork-juju`

Does exactly what it says, and it does it pretty well.

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

`jhack utils show-relation prometheus-k8s/0:ingress traefik-k8s/0:ingress-per-unit --watch`

Will pprint:

```bash
                                          relation data v0.1                                           
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ category         ┃     keys ┃ prometheus-k8s/0                                 ┃ traefik-k8s/0      ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ metadata         │ endpoint │ 'ingress'                                        │ 'ingress-per-unit' │
│                  │   leader │ True                                             │ True               │
├──────────────────┼──────────┼──────────────────────────────────────────────────┼────────────────────┤
│ application data │     data │ ingress:                                         │                    │
│                  │          │   prometheus-k8s/0:                              │                    │
│                  │          │     url: http://foo.bar:80/test-prometheus-k8s-0 │                    │
│ unit data        │     data │ host: 10.1.232.174                               │                    │
│                  │          │ model: test                                      │                    │
│                  │          │ name: prometheus-k8s/0                           │                    │
│                  │          │ port: 9090                                       │                    │
└──────────────────┴──────────┴──────────────────────────────────────────────────┴────────────────────┘
```

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
