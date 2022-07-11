from dataclasses import dataclass
from multiprocessing.pool import ThreadPool
from subprocess import Popen, PIPE
from time import sleep
from typing import Optional, Literal, List, Callable

import typer

from jhack.config import JUJU_COMMAND
from jhack.helpers import juju_status, juju_models, current_model, list_models
from jhack.logger import logger


@dataclass
class Endpoints:
    provider: str
    requirer: str


@dataclass
class Nukeable:
    name: str
    type: Literal['model', 'app', 'relation']

    # only applies to relations
    endpoints: Endpoints = None

    # model the nukeable is in, only applies to apps and relations
    model: str = None

    def __repr__(self):
        if self.type == 'model':
            return f"model {self.name!r}"
        elif self.type == 'app':
            return f"app {self.name!r} ({self.model})"
        else: # relation
            return f"relation {self.endpoints.provider!r} --> {self.endpoints.requirer}"


def _get_models(filter_):
    """List of existing models."""
    models = juju_models()
    found = 0
    _models = []
    for line in models.split('\n'):
        if line.startswith('Model '):
            found = 1
            continue
        if found and not line:
            break  # end of section
        if found:
            model_name = line.split()[0]
            if filter_(model_name):
                _models.append(model_name)
    if 'controller' in _models:
        _models.remove('controller')  # shouldn't try to nuke that one!
    return tuple(Nukeable(m, 'model') for m in _models)


def _get_apps_and_relations(model: Optional[str],
                            borked: bool,
                            filter_: Callable[[str], bool]) -> List[Nukeable]:
    status = juju_status("", model)
    apps = 0
    relation = 0
    nukeables = []
    for line in status.split('\n'):
        if line.startswith('App '):
            apps = 1
            continue

        if line.startswith('Relation '):
            relation = 1
            apps = 0
            continue
        if not line.strip():
            continue

        if apps:
            if borked and 'active' in line:
                continue
            app_name = line.split()[0].strip('*')
            if '/' in app_name:
                # unit; can't nuke those yet
                continue
            if filter_(app_name):
                nukeables.append(Nukeable(app_name, 'app', model=model))

        if relation:
            prov, req, *_ = line.split(' ')
            eps = Endpoints(prov.strip(), req.strip())
            if filter_(eps.provider) or filter_(eps.requirer):
                nukeables.append(Nukeable(f'{prov} {req}', 'relation',
                                          endpoints=eps))

    return nukeables


def _gather_nukeables(obj: Optional[str], model: Optional[str], borked: bool):
    globber = lambda s: s.startswith(obj)

    if isinstance(obj, str):
        if '*' in obj and '!' in obj:
            raise RuntimeError('combinations of ! and * not supported.')

        if obj.startswith('!'):
            globber = lambda s: obj.strip('!') == s
        elif '!' in obj:
            raise RuntimeError('! is only supported at the start of the name.')

        if obj.startswith('*') and obj.endswith('*'):
            globber = lambda s: obj.strip('*') in s
        elif obj.startswith('*'):
            globber = lambda s: s.endswith(obj.strip('*'))
        elif obj.endswith('*'):
            globber = lambda s: s.startswith(obj.strip('*'))

        obj = obj.strip('*!')

    nukeables: List[Nukeable] = []

    nukeables.extend(
        _get_apps_and_relations(model or current_model(),
                                borked=borked,
                                filter_=globber)
    )
    # if we passed a model, we mean 'nuke something in that model'
    # otherwise, we may be interested in nuking the models themselves.
    if not model:
        for model_ in list_models(strip_star=True):
            if model_ == 'controller':
                continue
            if globber(model_):
                nukeables.append(Nukeable(model_, 'model'))

    return nukeables


def _nuke(obj: Optional[str], model: Optional[str], borked: bool,
          n: int = None,
          dry_run: bool = False):
    if obj is None and not borked:
        nukeables = [Nukeable(current_model(), 'model')]
    else:
        nukeables = _gather_nukeables(obj, model, borked=borked)

    nukes = []
    nuked_apps = set()
    nuked_models = set()

    for nukeable in tuple(nukeables):
        if nukeable.type == 'model':
            nuked_models.add(nukeable.name)
            nukes.append(f"{JUJU_COMMAND} destroy-model {nukeable.name} "
                         f"--force --no-wait --destroy-storage -y")

        elif nukeable.type == 'app':
            nuked_apps.add(nukeable.name)

            assert nukeable.model, f'app {nukeable.name} has unknown model'
            if nukeable.model in nuked_models:
                nukeables.remove(nukeable)
                continue

            nukes.append(f"{JUJU_COMMAND} remove-application {nukeable.name} "
                         f"--force --no-wait")

        elif nukeable.type == 'relation':
            # if we're already nuking either app, let's skip nuking the relation
            assert nukeable.endpoints, f'relation {nukeable.name} has unknown endpoints'
            provider = nukeable.endpoints.provider
            requirer = nukeable.endpoints.requirer
            if (
                    provider.split(':')[0] in nuked_apps or
                    requirer.split(':')[0] in nuked_apps
            ):
                nukeables.remove(nukeable)
                continue

            nukes.append(
                f"{JUJU_COMMAND} remove-relation {provider} {requirer}")

        else:
            raise ValueError(nukeable.type)

    if n is not None:
        if n != (real_n := len(nukeables)):
            logger.debug(f"Unexpected number of nukeables; "
                         f"expected {n}, got: {nukeables}")
            for nukeable in nukeables:
                print(f'would ⚛ {nukeable}')
            word = 'less' if n > real_n else 'more'
            print(f'\nThat is {word} than what you expected. Aborting...')
            return

    if not nukeables:
        print('Nothing to ⚛.')
        return

    if dry_run:
        for nukeable in nukeables:
            print(f'would ⚛ {nukeable}')
        return

    def fire(nukeable: Nukeable, nuke: str):
        """defcon 5"""
        print(f'nuking ⚛ {nukeable} ⚛')
        logger.debug(f'nuking {nukeable} with {nuke}')
        proc = Popen(nuke.split(' '), stdout=PIPE, stderr=PIPE)
        proc.wait()
        while proc.returncode is None:
            sleep(.1)
        if proc.returncode != 0:
            print(f'something went wrong nuking {nukeable.name};'
                  f'stdout={proc.stdout.read().decode("utf-8")}'
                  f'stderr={proc.stderr.read().decode("utf-8")}')
        else:
            logger.debug(f'hit and sunk')

    tp = ThreadPool()
    for nukeable, nuke in zip(nukeables, nukes):
        tp.apply_async(fire, (nukeable, nuke))

    tp.close()
    tp.join()

    if not dry_run:
        print("✞ RIP ✞")


def nuke(what: List[str] = typer.Argument(..., help="What to ⚛."),
         model: Optional[str] = typer.Option(
             None, '-m', '--model',
             help='The model. Defaults to current model.'),
         n: Optional[int] = typer.Option(
             None, '-n', '--number',
             help="Exact number of things you're expected to be nuking."
                  "Safety first."),
         borked: bool = typer.Option(
             None, '-b', '--borked',
             help='Nukes all borked applications in current or target model.'),
         dry_run: bool = typer.Option(
             None, '--dry-run',
             help='Do nothing, print out what would have happened.')):
    """Surgical carpet bombing tool.

    Attempts to guess what you want to burn, and rains holy vengeance upon it.

    Examples:
        $ jhack nuke
        will vanquish the current model
        $ jhack nuke test-foo-*
        will bomb all nukeables starting with `test-foo-` , including:
         - models
         - applications
         - relations
        $ jhack nuke --model foo bar-*
        will bomb all nukeables starting with `bar-` in model foo. As above.
        $ jhack nuke -n=2 *foo*
        will blow up the two things it can find that contain the substring "foo"
    """
    if n is not None:
        assert n > 0, f'nonsense: {n}'
        if not len(what) == 1:
            print('You cannot use `-n` with multiple targets.')
    if not what:
        _nuke(None, model=model, borked=borked, n=n, dry_run=dry_run)
    for obj in what:
        _nuke(obj, model=model, borked=borked, n=n, dry_run=dry_run)


if __name__ == '__main__':
    nuke(["!foo"],
         n=None,
         model=None,
         borked=False,
         dry_run=True)
