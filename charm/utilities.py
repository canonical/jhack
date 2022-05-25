import contextlib
import os


@contextlib.contextmanager
def cwd(dir_):
    old_cwd = os.getcwd()
    os.chdir(dir_)
    yield
    os.chdir(old_cwd)
