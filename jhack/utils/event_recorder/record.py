from pathlib import Path
from subprocess import check_call

PAYLOAD = Path(__file__).parent / 'payload.py'
RECORDER_SOURCE = Path(__file__).parent / 'recorder.py'


def _copy_recorder_script(unit: str):
    unit_sanitized = unit.replace('/', '-')
    cmd = f"juju scp {RECORDER_SOURCE} " \
          f"{unit}:/var/lib/juju/agents/unit-{unit_sanitized}/charm/src/recorder.py"
    check_call(cmd.split())


def _inject_recorder_call(unit: str):
    unit_sanitized = unit.replace('/', '-')
    payload_txt = PAYLOAD.read_text()
    # escape all double quotes
    payload_txt.replace(r'"', r'\"')  # replace " with \"
    # e.g. '# here is charm code\n# if __name__ == '__main__':\n    # main(MyCharm)\n\n    from recorder import record\n    record()\n\n'
    cmd = ["juju", "exec", "--unit", unit, f"bash -c \"echo '{payload_txt}' >> /var/lib/juju/agents/unit-{unit_sanitized}/charm/src/charm.py\""]
    check_call(cmd)


def _install(unit: str):
    print('Shelling over recorder script...')
    _copy_recorder_script(unit)
    print('Injecting recorder call...')
    _inject_recorder_call(unit)
    print('Recorder installed.')


def install(unit: str):
    """Install the record spyware on the given unit."""
    return _install(unit)


if __name__ == '__main__':
    _install('trfk/1')

