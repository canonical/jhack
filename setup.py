import os

from setuptools import find_packages, setup


def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()


setup(
    name="jhack",
    version="0.3.2",
    author="Pietro Pasotti",
    author_email="pietro.pasotti@canonical.com",
    description=("Cli tool with juju hacks."),
    license="Apache 2.0",
    keywords="juju hacks cli charm charming",
    url="https://github.com/PietroPasotti/jhack",
    packages=find_packages(),
    long_description=read("README.md"),
    requires=[
        "typer(==0.4.1)",
        "ops(==1.5.3)",
        "rich(==12.0.1)",
        "parse(==1.19.0)",
        "juju(==2.9.7)",
        "asttokens",
        "astunparse",
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Topic :: Utilities",
        "License :: OSI Approved :: Apache Software License",
    ],
    entry_points={"console_scripts": ["jhack = jhack.main:main"]},
    package_data={
        '': ['unbork_juju']
    }
)
