from pathlib import Path

import pytest
from mock import mock

from utils.show_relation import sync_show_relation

cmd_to_output_mocks = {
    'machine':
        {['juju', 'show-unit', 'ceilometer/0']: 'ceil0_show.txt',
         ['juju', 'show-unit', 'mongo/0']: 'mongo0_show.txt',
         ['juju', 'status', 'ceilometer', '--relations']: 'ceil_status.txt',
         ['juju', 'status', 'mongo', '--relations']: 'mongo_status.txt'},
    'k8s':
        {['juju', 'show-unit', 'traefik-k8s/0']: 'traefik0_show.txt',
         ['juju', 'show-unit', 'prometheus-k8s/0']: 'prom0_show.txt',
         ['juju', 'status', 'traefik-k8s', '--relations']: 'traefik_status.txt',
         ['juju', 'status', 'prometheus-k8s', '--relations']: 'prom_status.txt'},

}


@mock.patch("subprocess.Popen")
@pytest.fixture(params=['machine', 'k8s'])
def env(request):
    return request.param


@pytest.fixture(autouse=True)
def mock_stdout(mock_subproc_popen, request, env):
    class StdoutMock:
        def read(self) -> bytes:
            args = mock_subproc_popen.args
            mock_file_name = cmd_to_output_mocks[request.param][args]
            mock_file = Path(__file__).parent / 'show_relation_mocks' / request.param / mock_file_name
            return mock_file.read_text().encode('utf-8')

    stdout = mock_subproc_popen.stdout
    mock_subproc_popen.stdout = StdoutMock()

    yield

    mock_subproc_popen.stdout = stdout


def est_show_unit_works(env):
    if env == 'k8s':
        sync_show_relation("traefik-k8s:ingress-per-unit",
                           "prometheus-k8s:ingress")
    else:
        sync_show_relation("ceilometer:shared-db", "mongo:database")
