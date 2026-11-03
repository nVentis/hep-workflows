"""Consistency checks of the configurations in hep_workflows/configs and of law.cfg, which can be done
without a software stack: the configurations are only imported, none of the tasks is run."""

import importlib
import importlib.util
import inspect
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest

from hep_workflows.framework import AnalysisConfiguration, EVENT_SIM_ENUM, RECO_ANA_RUNMODES, configurations

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LAW_CFG = PACKAGE_DIR.parent / 'law.cfg'
CONFIG_MODULES = sorted(f'hep_workflows.configs.{p.stem}' for p in (PACKAGE_DIR / 'configs').glob('test_*.py'))
POLARIZATION_KEYS = {'eL.pL', 'eL.pR', 'eR.pL', 'eR.pR'}

# importing registers the configurations (setup() is only called on first use, i.e. never here)
for name in CONFIG_MODULES:
    importlib.import_module(name)

CONFIGS:list[AnalysisConfiguration] = [config for config in configurations.definitions.values() if type(config).__module__ in CONFIG_MODULES]
parametrize_configs = pytest.mark.parametrize('config', CONFIGS, ids=lambda config: config.tag)

def law_cfg_modules()->list[str]:
    modules, in_section = [], False

    for line in map(str.strip, LAW_CFG.read_text().splitlines()):
        if line.startswith('['):
            in_section = line == '[modules]'
        elif in_section and line and not line.startswith('#'):
            modules.append(line)

    return modules

@pytest.fixture(scope='module', autouse=True)
def analysis_path():
    # as set by setup.sh
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv('ANALYSIS_PATH', str(PACKAGE_DIR))
        yield

@pytest.mark.skipif(not LAW_CFG.is_file(), reason='law.cfg not found (package not installed from the repository)')
class TestLawCfg:
    def test_all_modules_are_importable(self):
        for name in law_cfg_modules():
            assert importlib.util.find_spec(name) is not None, f'law.cfg lists module <{name}> which does not exist'

    def test_all_configurations_are_listed(self):
        missing = set(CONFIG_MODULES) - set(law_cfg_modules())
        assert not missing, f'Configuration modules missing in law.cfg [modules]: {sorted(missing)}'

def test_configurations_exist():
    assert len(CONFIGS) > 0

def test_modules_register_at_most_one_configuration_and_tags_are_unique():
    # test_e550_bbbb only defines tasks and registers none
    assert max(Counter(type(config).__module__ for config in CONFIGS).values()) == 1
    assert len({config.tag for config in CONFIGS}) == len(CONFIGS)

@parametrize_configs
def test_docstring_shows_how_to_run(config):
    module = type(config).__module__
    doc = sys.modules[module].__doc__ or ''

    assert f'--tag={config.tag}' in doc, f'{module}: the docstring does not show the tag <{config.tag}>'
    assert f'--module {module}' in doc, f'{module}: the docstring does not show how to select the module'

@parametrize_configs
def test_setup_is_a_method(config):
    # setup() is called on the instance by the registry
    assert inspect.ismethod(config.setup)
    inspect.signature(config.setup).bind()

@parametrize_configs
def test_stages(config):
    assert config.simulation in tuple(EVENT_SIM_ENUM)
    assert config.high_level_reco in tuple(RECO_ANA_RUNMODES)
    assert config.analysis in tuple(RECO_ANA_RUNMODES)
    assert config.low_level_reco == (None if config.simulation == EVENT_SIM_ENUM.FAST_SGV else RECO_ANA_RUNMODES.K4RUN)

@parametrize_configs
def test_simulation_input(config):
    if config.simulation == EVENT_SIM_ENUM.FAST_SGV:
        assert isinstance(config.sgv_inputs, Callable), 'fast simulation requires sgv_inputs'
        assert config.high_level_reco_input_files is not None
    else:
        assert config.generator_files is not None, 'full simulation requires generator_files'

@parametrize_configs
@pytest.mark.parametrize('stage, cls', [('high_level_reco', 'RecoAbstract'), ('analysis', 'AnalysisAbstract')])
def test_reco_ana_stage(config, stage, cls):
    """k4run stages need a compact file; k4run steering files are Python, Marlin steering files XML"""
    if cls not in config.task_kwargs:
        pytest.skip(f'{stage} is not configured')

    kwargs = {**config.task_kwargs.get('RecoAnaBaseJob', {}), **config.task_kwargs[cls]}

    if config.uses_k4run(stage):
        assert kwargs.get('compact_file'), f'{stage} runs k4run, but no compact_file is given'

    if 'steering_file' in kwargs:
        assert kwargs['steering_file'].endswith('.py' if config.uses_k4run(stage) else '.xml'), \
            f'steering_file {kwargs["steering_file"]} does not fit {getattr(config, stage).value}'

@parametrize_configs
def test_referenced_files_exist(config):
    for cls, kwargs in config.task_kwargs.items():
        for key, value in kwargs.items():
            if isinstance(value, str) and value.startswith('$ANALYSIS_PATH/'):
                path = Path(os.path.expandvars(value))
                assert path.is_file(), f'task_kwargs[{cls}][{key}] points to {path}, which does not exist'

@parametrize_configs
def test_whizard_options(config):
    for option in config.whizard_options or []:
        template_dir = Path(os.path.expandvars(option['template_dir']))
        sindarin_file = template_dir / option['sindarin_file']

        assert sindarin_file.is_file(), f'{sindarin_file} does not exist'
        assert set(option['iters_per_polarization'] or {}) <= POLARIZATION_KEYS

        sindarin = sindarin_file.read_text()

        # the process must be defined exactly once, either in the template or in process_definition
        name = option['process_name']
        definition = re.compile(rf'^\s*process\s+{re.escape(name)}\s*=', re.MULTILINE)
        n_defined = len(definition.findall(sindarin)) + len(definition.findall(option.get('process_definition', '')))
        assert n_defined == 1, f'process <{name}> is defined {n_defined} times (in {sindarin_file.name} and process_definition)'

        circe = re.search(r'circe2_file\s*=\s*"([^"]+)"', sindarin)
        assert circe is None or (template_dir / circe.group(1)).is_file()

        # COM_ENERGY is hardcoded in the sindarin file
        sqrts = re.search(r'^\s*sqrts\s*=\s*(\d+)\s*GeV', sindarin, re.MULTILINE)
        assert sqrts is not None and float(sqrts.group(1)) == config.sqrt_s, f'sqrt_s does not fit {sindarin_file.name}'
