"""Minimal end-to-end configuration exercising the full-simulation chain starting with
Whizard-based event generation, SGV fast simulation and contiuing with Gaudi/k4run based
low-level-reconstruction, reconstruction and analysis. 

    law run AnalysisFinal --tag=250-e2e2h-ild-fast-marlin --module hep_workflows.configs.test_e250_zh_fast_marlin
"""

import os
import os.path as osp

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.utils.types import WhizardOption

class TestE250ZHFastK4RunConfig(AnalysisConfiguration):
    tag = '250-e2e2h-ild-fast-marlin'
    sqrt_s = 250.

    simulation = EVENT_SIM_ENUM.FAST_SGV

    high_level_reco = RECO_ANA_RUNMODES.K4RUN
    analysis = RECO_ANA_RUNMODES.K4RUN

    compact_file = '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml'

    task_kwargs = {
        'RecoAnaBaseJob': {
            'compact_file': compact_file,
            # cap the number of events if not given by the chunk plan, i.e. for RecoRuntime/AnalysisRuntime
            'n_events_max': 50,
        },
        'RecoAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/high_level_reco.py',
            'output_file': 'reco.edm4hep.root',
            'check_output_lcio_files': None,
        }
    }

    whizard_options: list[WhizardOption] = [{
        'process_name': 'e2e2h',
        'process_definition': 'process e2e2h = e1,E1 => e2, E2, h { $omega_flags = "-model:constant_width" }',
        'template_dir': '$ANALYSIS_PATH/resources/whizard_template',
        'sindarin_file': 'whizard.base250.sin',
        # only each one file for eL.pR and eP.pL polarizations
        'iters_per_polarization': {
            'eL.pR': 1,
            'eR.pL': 1
        },
        'nevents': 100,
    }]

    def setup():
        from .provisioning import provision_sgv, provision_ild_config

        provision_ild_config()
        provision_sgv()

configurations.add(TestE250ZHFastK4RunConfig())