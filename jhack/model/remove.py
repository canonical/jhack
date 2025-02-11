import typer


def rmodel(
    model_name=typer.Argument(
        None,
        help="comma-separated list of models to be removed, or single globbed name",
    ),
    force: bool = True,
    restart: bool = False,
    no_wait: bool = True,
    destroy_storage: bool = True,
    dry_run: bool = False,
):
    raise DeprecationWarning("deprecated. use nuke instead.")
