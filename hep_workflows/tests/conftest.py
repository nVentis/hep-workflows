"""Fixtures for the integration tests (marker `integration`): they run law in a subprocess in the software
environment defined by setup.sh, i.e. key4hep from CVMFS and the Python virtual environment
(PYTHON_ENVIRONMENT_PATH), as the batch jobs do. The unit tests do not need any of this.

The environment is taken from
- the file given in $HEP_WORKFLOWS_TEST_ENV, else $DOT_ENVIRONMENT_FILE, else hep_workflows/.env, if any of them exists
- the variables of the calling process (e.g. K4H_RELEASE, PYTHON_ENVIRONMENT_PATH in CI), which setup.sh
  does not overwrite unless they are also defined in the file.
DATA_PATH is always replaced with a temporary directory, so that no existing data is touched. Tests with a
nightly key4hep build as requirement (Scenario.needs_nightly in test_integration.py) are skipped unless K4H_NIGHTLY is set.
"""

import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
SETUP_SH = PACKAGE_DIR / 'setup.sh'
CVMFS_KEY4HEP = Path('/cvmfs/sw.hsf.org/key4hep')

def pytest_collection_modifyitems(config, items):
    if CVMFS_KEY4HEP.is_dir() and SETUP_SH.is_file():
        return

    skip = pytest.mark.skip(reason=f'{CVMFS_KEY4HEP} or {SETUP_SH} not found: key4hep is not available through CVMFS')
    for item in items:
        if 'integration' in item.keywords:
            item.add_marker(skip)

def parse_env_file(path:Path)->dict[str, str]:
    """Reads NAME=VALUE entries, as setup.sh does (no spaces; quotes are removed)"""
    matches = (re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)', line.strip()) for line in path.read_text().splitlines())

    return { m.group(1): m.group(2).strip('"\'') for m in matches if m is not None }

class SoftwareEnvironment:
    """Runs commands in the environment of setup.sh"""

    def __init__(self, workdir:Path, base_env_file:Path|None):
        self.workdir = workdir
        self.data_path = workdir / 'data'
        self.data_path.mkdir()

        entries = { **(parse_env_file(base_env_file) if base_env_file is not None else {}), 'DATA_PATH': str(self.data_path) }
        env_file = workdir / 'test.env'
        env_file.write_text(''.join(f'{key}="{value}"\n' for key, value in entries.items()))

        # setup.sh does not overwrite variables of the process unless they are in the file
        self.uses_nightly = bool({ **os.environ, **entries }.get('K4H_NIGHTLY'))

        # setup.sh loads the entries of this file
        self.process_env = { **os.environ, 'DOT_ENVIRONMENT_FILE': str(env_file),
                             # run the whole dependency tree locally, not on HTCondor (see BaseWorkflowTask)
                             'HEP_WORKFLOWS_DEFAULT_WORKFLOW': 'local' }

    def run(self, command:str, timeout:float|None=None)->subprocess.CompletedProcess:
        """Runs a shell command after sourcing setup.sh; the working directory is a temporary
        directory, as some of the software writes files (e.g. cdb.log) to it"""
        return subprocess.run(['bash', '-c', f'source {shlex.quote(str(SETUP_SH))} > /dev/null || exit 99; {command}'],
                              cwd=self.workdir, env=self.process_env, capture_output=True, text=True, timeout=timeout)

    def law(self, task:str, tag:str, module:str, *args:str, timeout:float|None=None)->subprocess.CompletedProcess:
        """Runs `law run <task>` with the local scheduler (the default of law.cfg)"""
        return self.run(shlex.join(['law', 'run', task, f'--tag={tag}', f'--module={module}', '--local-scheduler', *args]), timeout=timeout)

    def data_dir(self, task:str, tag:str)->Path:
        return self.data_path / task / tag

@pytest.fixture(scope='session')
def software_environment(tmp_path_factory)->SoftwareEnvironment:
    candidates = (os.environ.get('HEP_WORKFLOWS_TEST_ENV'), os.environ.get('DOT_ENVIRONMENT_FILE'), PACKAGE_DIR / '.env')
    base_env_file = next((Path(c) for c in candidates if c and Path(c).is_file()), None)

    env = SoftwareEnvironment(tmp_path_factory.mktemp('hep_workflows'), base_env_file)

    # setup.sh must find key4hep and the Python environment
    result = env.run('which law k4run Marlin whizard', timeout=600)
    if result.returncode != 0:
        pytest.skip(f'Could not set up the software environment with setup.sh (exit code {result.returncode}): {result.stderr or result.stdout}')

    return env
