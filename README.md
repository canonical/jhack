# jhack - Make charming charming again!

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

##### as snap:

    $ sudo snap install --edge jhack
    $ sudo snap connect jhack:dot-local-share-juju snapd

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


## show-stored

As we know, ops offers the possibility to use StoredState to persist some data between events, making charms therefore (somewhat) stateful. It can be challenging (or simply tedious) during testing and debugging, to inspect the contents of a live charm’s stored state in a uniform way.

Well, no more!

Suppose you have a prometheus-k8s charm deployed as `prom` (and related to traefik-k8s).
Type: `jhack show-stored prom/0` and you'd get:

```commandline
                                                      stored data v0.1                                                       
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ PrometheusCharm.GrafanaDashboardProvider._stored            ┃ PrometheusCharm.ingress._stored                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│                                                             │                                                            │
│  handle:  PrometheusCharm/GrafanaDashboardProvider[grafan…  │  handle:  PrometheusCharm/IngressPerUnitRequirer[ingress…  │
│    size:  8509b                                             │    size:  657b                                             │
│                           <dict>                            │                           <dict>                           │
│ ┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │ ┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │
│ ┃ key                   ┃ value                           ┃ │ ┃ key            ┃ value                                 ┃ │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │ ┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │
│ │ 'dashboard_templates' │ {'file:prometheus-k8s_rev1.jso… │ │ │ 'current_urls' │ {'prom/0':                            │ │
│ │                       │ {'charm': 'prometheus-k8s',     │ │ │                │ 'http://0.0.0.0:80/baz-prom-0'}       │ │
│ │                       │ 'content':                      │ │ └────────────────┴───────────────────────────────────────┘ │
│ │                       │ '/Td6WFoAAATm1rRGAgAhARYAAAB0L… │ │                                                            │
│ │                       │ 'juju_topology': {'model':      │ │                                                            $
│ │                       │ 'baz', 'model_uuid':            │ │                                                            │
│ │                       │ '00ff58ab-c187-497d-85b3-7cadd… │ │                                                            │
│ │                       │ 'application': 'prom', 'unit':  │ │                                                            │
│ │                       │ 'prom/0'}}}                     │ │                                                            │
│ └───────────────────────┴─────────────────────────────────┘ │                                                            │
└─────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘
```

### Adapters
The bottom part of the two table cells contains the ‘blob’ itself. At the moment we only implement ‘pretty-printers’ for python dicts. ops natively serializes only native python datatypes (anything you can `yaml.dump, in fact), but you could be serializing much more complex stuff than that.

For that reason, `jhack show-stored` exposes an `--adapters` optional argument, which allows you to inject your custom adapter to deserialize a specific handle. So, for example, if you are not happy with how the ingress `StoredData` is represented, you could create a file:

```python
from urllib.parse import urlparse
from rich.table import Table
def _deserialize_ingress(raw: dict):
    urls = raw['current_urls']
    table = Table(title='ingress view adapter')
    table.add_column('unit')
    table.add_column('scheme')
    table.add_column('hostname')
    table.add_column('port')
    table.add_column('path')

    for unit_name, url in urls.items():
        row = [unit_name]

        p_url = urlparse(url)
        hostname, port = p_url.netloc.split(":")
        row.extend((p_url.scheme, hostname, port, p_url.path))

        table.add_row(*row)

    return table  # we can return any rich.RenderableType (str, or Rich builtins)

# For this to work, this file needs to declare a global 'adapters' var of the right type.
adapters = {
    "PrometheusCharm/IngressPerUnitRequirer[ingress]/StoredStateData[_stored]": _deserialize_ingress
}
```
And then by running jhack show-stored -a /path/to/that/file, you’d magically get:

```commandline
                                                      stored data v0.1                                                       
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ PrometheusCharm.GrafanaDashboardProvider._stored            ┃ PrometheusCharm.ingress._stored                            ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│                                                             │                                                            │
│  handle:  PrometheusCharm/GrafanaDashboardProvider[grafan…  │  handle:  PrometheusCharm/IngressPerUnitRequirer[ingress…  │
│    size:  8509b                                             │    size:  657b                                             │
│                           <dict>                            │                ingress view adapter                        │
│ ┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓ │ ┏━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━━┓        │
│ ┃ key                   ┃ value                           ┃ │ ┃ unit   ┃ scheme ┃ hostname ┃ port ┃ path        ┃        │
│ ┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩ │ ┡━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━━┩        │
│ │ 'dashboard_templates' │ {'file:prometheus-k8s_rev1.jso… │ │ │ prom/0 │ http   │ 0.0.0.0  │ 80   │ /baz-prom-0 │        │
│ │                       │ {'charm': 'prometheus-k8s',     │ │ └────────┴────────┴──────────┴──────┴─────────────┘        │
│ │                       │ 'content':                      │ │                                                            │
│ │                       │ '/Td6WFoAAATm1rRGAgAhARYAAAB0L… │ │                                                            │
│ │                       │ 'juju_topology': {'model':      │ │                                                            │
│ │                       │ 'baz', 'model_uuid':            │ │                                                            │
│ │                       │ '00ff58ab-c187-497d-85b3-7cadd… │ │                                                            │
│ │                       │ 'application': 'prom', 'unit':  │ │                                                            │
│ │                       │ 'prom/0'}}}                     │ │                                                            │
│ └───────────────────────┴─────────────────────────────────┘ │                                                            │
└─────────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘
```

Which is pretty cool.

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

By using this tool you acknowledge the possibility of it bricking your model or controller. Hopefully nothing beyond that.

### Safety tips
- Learn to use the command by trying out the `--dry-run` flag first, that will print out what it would nuke without actually nuking anything.
- The command has an optional `-n` flag that allows you to specify the expected number of nukes that should be fired out. If more or less than `n` nukeables are matched, the command will print an error message and abort.
- The command has a `--selectors` (`-s`) option that can be used to specify what to include/exclude in the bombardment.
    - 'a' for apps, 'A' for all except apps
    - 'm' for models, 'M' for all except models
    - 'r' for relations, 'R' for all except relations
      (although, the resulting nuke will probably also wipe the relations that would have been matched had this flag been omitted)

  So, for example, `jhack nuke -s M foo` will nuke all apps and relations it can find matching 'foo', equivalent to `jhack nuke -s ar foo`.


# fire

This command is used to simulate a specific event on a live unit. It works by building up an environment from scratch and tricking the charm to think a specific event is running by using `juju exec`. You can use it to simulate `update-status`, and other 'simple' events that have no special requirements in terms of envvars being set, but also more complex events are supported (relation events, workload events).

Examples:

`jhack fire traefik/0 update-status`

`jhack fire traefik/0 ingress-per-unit-relation-changed`

Pro tip: use `fire` it in combination with `jhack sync` to quickly iterate and repeatedly execute the charm 'as if' a specific event was being fired.

Caveats:
careless usage can rapidly and irrevocably bork your charm, since the events being fired in this way are not real juju events, therefore the charm state and the juju state can rapidly desync. E.g. Juju thinks everything is fine with the charm, but you just simulated a 'remove' event, following which the charm duly stopped all workload services, cleared a database and got ready to gracefully teardown. If after that Juju decides to fire any event, the charm will rightfully be surprised because it thought it was about to be killed.

However, if all of your event handlers truly are idempotent (hem hem) you should be *fine*.


# replay
This command offers facilities to capture runtime event contexts and use them to 're-fire' "the same event" later on.
Unlike `jhack utils fire`, which uses a synthetic (i.e. built from scratch, minimal) environment, this command family gets a hold of a 'real' environment, serializes it, and reuses it as needed. So the env is more complete. 
The flow consists of two main steps:
- inject code that captures any event, serializes it and dumps it to a db on the unit.
- whenever you like, trigger a charm execution reusing a recorded context.


## install

This command is used to inject into a unit the code responsible for capturing the context in which the charm runs and dropping it to a db file.

Example usage:

    jhack replay install trfk/0

## list

This command is used to enumerate, first to last, all events which have been fired onto a unit (since replay was installed!).
You can use the index of the enumeration to later re-fire the event.

Example:

    jhack replay list trfk/0

its output could be something like:

    Listing recorded events:                                                     
        (0) 2022-09-12 11:54:02.279174 :: start                              
        (1) 2022-09-12 11:54:02.768836 :: ingress-per-unit-relation-created  
        (2) 2022-09-12 11:54:03.293178 :: ingress-per-unit-relation-joined   
        (3) 2022-09-12 11:54:03.810452 :: ingress-per-unit-relation-changed  
        (4) 2022-09-12 11:54:04.369351 :: ingress-per-unit-relation-joined   
        (5) 2022-09-12 11:54:04.924288 :: ingress-per-unit-relation-changed  
        (6) 2022-09-12 11:54:10.371510 :: traefik-pebble-ready

or if no events have been fired yet:

    Listing recorded events:
        <no events>                                                          


Tip: to quickly get some events in, you could `jhack fire trfr/0 update-status`.

## emit

This command is used to re-fire a recorded event onto the same unit.

    jhack replay emit trfk/0 2

Note that the index needs to match that of some recorded event (you can inspect those with `jhack replay list`).

Example run:

    $ jhack replay install trfk/0
    $ jhack replay list trfk/0
    Listing recorded events:
        (0) 2022-09-12 11:54:02.279174 :: start                             
        (1) 2022-09-12 11:54:02.768836 :: ingress-per-unit-relation-created 
        (2) 2022-09-12 11:54:03.293178 :: ingress-per-unit-relation-joined  
        (3) 2022-09-12 11:54:03.810452 :: ingress-per-unit-relation-changed 
    $ jhack replay emit trfk/0 2
    Replaying event (3): ingress-per-unit-relation-joined as originally emitted at 2022-09-12 11:54:03.293178.

## dump

Dump a recorded event (raw json).
Interesting if you want to inspect the event context, or if you want to re-use it in other scripts (e.g. with `jhack utils fire`).


## Runtime

In `jhack.utils.event_recorder.runtime` you can find a Runtime class. That object can be used, in combination with the json database you obtained via `replay dump`, to locally execute a charm by simulating the context "exactly" as it occurred during the recorded execution.

At some point it will be moved to a charm lib.

The main use cases for Runtime are:
- regression testing: 
  - install replay on some unit, 
  - wait for some event to bork your charm
  - grab the event db and put it in some /tests/replay_data folder 
  - use Runtime to mock a charm execution using that backing database so that the charm will 
    run again "exactly as it did back then"
  - Assert that the charm does not bork exactly as it did back then
- local debugging:
  - use your favourite ide debugger tool to step through charm code without having to do 
    any mocking **at all**: all juju-facing calls will return 'as they did in real life'.

Future work:
- make it easier to manually edit the contents of the event database, to turn Runtime into a 
  Scenario mocking lib. What if instead of returning True, leader-get returned False at that point?
- Reuse the @memo injection facilities to reroute locally originating juju/pebble client calls 
  to a specific remote controller and pebble server. Goal: be able to run a charm ANYWHERE but 
  have it talk to a real backend living somewhere else.


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

## provision

Run a script in one or multiple units.

When debugging, it's often handy to install certain tools on a running unit, to then shell into it and start hacking around.
How often have you:
```
juju ssh foo/0
apt update
apt install vim procps top mc -y
```

Well, no more!

The idea is: you create your unit provisioning script in `~/.cprov/default`, keeping in mind that no user input can be expected (i.e. put `-y` flags everywhere).

Running 
> jhack charm provision traefik-k8s/1;prometheus-k8s

will run that script on all prometheus units, and traefik's unit `1`.
You can put multiple scripts in `~/.cprov`, and choose which one to use by:
> jhack charm provision foo/1 --script foo

Alternatively, you can pass a full path, and it will not matter where the file is:
> jhack charm provision foo/1 --script /path/to/your/script.sh

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
