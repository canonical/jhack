# Contributing

![GitHub License](https://img.shields.io/github/license/canonical/jhack)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/jhack)
![GitHub Lines of Code](https://img.shields.io/tokei/lines/github/canonical/jhack)
![GitHub Issues](https://img.shields.io/github/issues/canonical/jhack)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/jhack)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/jhack)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/jhack?style=social)

This documents explains the processes and practices recommended for contributing code to this bowl of spaghetti.

- Generally, before developing enhancements to this repo, you should consider [opening an issue](https://github.com/canonical/jhack/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at the [Charm devtools Matrix public channel](https://matrix.to/#/#charmhub-charmdevtools:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).
- All enhancements require review before being merged. Code review typically examines (in order of importance):
  - code quality
  - user experience
  - test robustness
- When evaluating design decisions, we optimize for the following personas, in descending order of priority:
  - charm developers that want to debug the charm or troubleshoot their deployment
  - the contributors to this codebase
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Notable design decisions

**The CLI tree:** 
Jhack is a CLI tool offering a single entrypoint: the `jhack` command.
Jhack has then a number of subcommands that correspond to categories of tools. At the time of writing these are:

- `charm`: Charmcrafting utilities
- `replay`: Commands to replay events
- `imatrix`: Commands to view and manage the integration matrix
- `conf`: Jhack configuration
- `scenario`: Commands to interact with scenario-powered State
- `chaos`: Chaos testing tools
- `utils`: Mixed salad of charming utilities

Mounted on the toplevel `jhack` command are also a number of shortcuts to the most commonly used tools.
For example `jhack utils show-relation` is also available at `jhack show-relation`. Same for `jhack ffwd, jenv, sync, charm-info, fire, eval...` et cetera.

## Developing

To set up a local development environment with `uv`:

    uv venv
    uv pip install --all-extras -r pyproject.toml  


On my local system I usually have a local jhack install (from sources) _and_ the snap installed.
I achieve this by:

    ln -s ~/bin/ljhack /path/to/jhack/jhack/main.py
    chmod +x ~/bin/ljhack

Now I have the jhack snap available under `jhack` in my shell, and the "local" jhack install (from source) available at `ljhack`. That's excellent for development.


### Contributing

If you're a regular contributor you may want to request to be given contributor access to the repo; but usually it's easier and faster if you create a fork and submit your PRs from there.

### Testing

```shell
make fmt           # update your code according to linting and formatting rules
make unit          # unit tests
```

### Snap

To build and install the jhack snap you should run:

    sudo snap remove --purge jhack  # if you already have one installed
    snapcraft pack
    sudo snap install --dangerous ./jhack_<built-version>_amd64.snap

To debug the snap, it can be handy to run `snappy-debug` to see what error logs (and apparmor failures) the snap is encountering, and `snap run --shell jhack` to ssh into the snap env and 'see what it sees'