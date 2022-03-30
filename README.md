# utils
## sync

`jhack utils sync ./src application-name/0`

Will watch the ./src folder for changes and push any to application-name/0 
under /charm/src/.

## unfuck-juju

`jhack utils unfuck-juju`

Does exactly what it says, and it does it pretty well.

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


