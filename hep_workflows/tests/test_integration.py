"""Integration tests: for each configuration in hep_workflows/configs, law is run in the software
environment of setup.sh (see conftest.py) up to RecoFinal, using the configurations' small samples.
They cover the combinations of fast (SGV)/full (ddsim) simulation and Marlin/k4run for the stages:

    fast-marlin: Whizard -> SGV -> Marlin reconstruction
    fast-k4run:  Whizard -> SGV -> k4run reconstruction
    full-k4run:  Whizard -> ddsim -> k4run low-level reconstruction -> k4run reconstruction

Run with `pytest -m integration`. The dependencies of the configurations (SGV, ILDConfig) are installed by their setup()
if $SGV_DIR/$ILD_CONFIG_DIR do not exist; note that SGV is built against the stack in use.
"""

import re
import shlex
from dataclasses import dataclass

import numpy as np
import pytest

from .conftest import SoftwareEnvironment

pytestmark = pytest.mark.integration

LCIO = ('*.slcio', 'lcio_event_counter')
EDM4HEP = ('*.edm4hep.root', 'edm4hep_event_counter')
FAST_SIM_TASKS = ['WhizardEventGeneration', 'GeneratorIndex', 'FastSimSGV', 'RawIndex', 'CreateRecoChunks', 'RecoFinal']
FULL_SIM_TASKS = ['WhizardEventGeneration', 'GeneratorIndex', 'DDSimFinal', 'LowLevelRecoFinal', 'RawIndex', 'CreateRecoChunks', 'RecoFinal']

@dataclass
class Scenario:
    name: str
    # key4hep nightly build required (k4run steering files, ddsim)
    needs_nightly: bool
    # tasks that have to be (not) part of the dependency tree of RecoFinal
    tasks: list[str]
    absent_tasks: list[str]
    # task -> (glob of the files that must exist in its data directory, name of the event counter)
    outputs: dict[str, tuple[str, str]]

    @property
    def module(self)->str:
        return f'hep_workflows.configs.test_e250_zh_{self.name.replace("-", "_")}'

    @property
    def tag(self)->str:
        return f'250-e2e2h-ild-{self.name}'

SCENARIOS = [
    Scenario('fast-marlin', False, FAST_SIM_TASKS, ['DDSimFinal', 'LowLevelRecoFinal'],
             { 'WhizardEventGeneration': LCIO, 'FastSimSGV': LCIO, 'RecoFinal': LCIO }),
    Scenario('fast-k4run', True, FAST_SIM_TASKS, ['DDSimFinal', 'LowLevelRecoFinal'],
             { 'WhizardEventGeneration': LCIO, 'FastSimSGV': LCIO, 'RecoFinal': EDM4HEP }),
    Scenario('full-k4run', True, FULL_SIM_TASKS, ['FastSimSGV'],
             { 'WhizardEventGeneration': LCIO, 'DDSimFinal': EDM4HEP, 'LowLevelRecoFinal': EDM4HEP, 'RecoFinal': EDM4HEP }),
]
SCENARIO_PARAMS = [pytest.param(scenario, id=scenario.name) for scenario in SCENARIOS]

@pytest.mark.parametrize('scenario', SCENARIO_PARAMS)
def test_dependency_tree(scenario:Scenario, software_environment:SoftwareEnvironment):
    """The configuration injects the tasks of its simulation and its stages; nothing is run"""
    result = software_environment.law('RecoFinal', scenario.tag, scenario.module, '--print-deps', '20', timeout=900)
    assert result.returncode == 0, result.stderr[-3000:]

    tasks = set(re.findall(r'> (\w+)', result.stdout))

    assert set(scenario.tasks) <= tasks, f'missing in the dependency tree of RecoFinal: {sorted(set(scenario.tasks) - tasks)}'
    assert not set(scenario.absent_tasks) & tasks, f'must not be in the dependency tree of RecoFinal: {sorted(set(scenario.absent_tasks) & tasks)}'

@pytest.fixture(scope='module', params=SCENARIO_PARAMS)
def completed_run(request, software_environment:SoftwareEnvironment):
    """Runs the whole chain up to RecoFinal once per scenario"""
    scenario:Scenario = request.param
    if scenario.needs_nightly and not software_environment.uses_nightly:
        pytest.skip(f'{scenario.name} requires a key4hep nightly build: set K4H_NIGHTLY (see README)')

    result = software_environment.law('RecoFinal', scenario.tag, scenario.module, timeout=3 * 3600)

    return scenario, software_environment, result

def successful_run(completed_run):
    scenario, env, result = completed_run
    if result.returncode != 0:
        pytest.skip('the chain failed, see test_chain_succeeds')

    return scenario, env

def test_chain_succeeds(completed_run):
    scenario, env, result = completed_run
    output = result.stdout + result.stderr

    assert result.returncode == 0 and 'This progress looks :)' in output, f'law run RecoFinal failed for <{scenario.tag}>:\n{output[-6000:]}'

def test_outputs_exist_and_have_events(completed_run):
    scenario, env = successful_run(completed_run)

    for task, (pattern, counter) in scenario.outputs.items():
        files = sorted(env.data_dir(task, scenario.tag).glob(pattern))
        assert files, f'{task} did not produce any {pattern} in {env.data_dir(task, scenario.tag)}'

        for file in files:
            count = env.run(f'{counter} {shlex.quote(str(file))}', timeout=300)

            assert count.returncode == 0, count.stderr
            assert int(count.stdout.strip().splitlines()[-1]) > 0, f'{file} contains no events'

def test_indices_are_consistent(completed_run):
    """RawIndex indexes the input of the reconstruction, with the processes of the configuration"""
    scenario, env = successful_run(completed_run)
    index_dir = env.data_dir('RawIndex', scenario.tag)
    samples, processes = np.load(index_dir / 'samples.npy'), np.load(index_dir / 'processes.npy')

    assert len(samples) > 0 and len(processes) > 0
    assert set(samples['process']) == {'e2e2h'}
    assert (samples['n_events'] > 0).all()
