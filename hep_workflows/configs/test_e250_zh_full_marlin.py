"""Minimal end-to-end configuration exercising the full-simulation chain with Gaudi/k4run based
low-level-reconstruction and Marlin-based high-level reconstruction and analysis. 

    law run AnalysisFinal --tag=250-e2e2h-ild-full-marlin --module hep_workflows.configs.test_e250_zh_full_marlin
"""

import os

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.utils.types import WhizardOption


class TestE250ZHFullK4RunConfig(AnalysisConfiguration):
    tag = '250-e2e2h-ild-full-marlin'
    sqrt_s = 250.

    # use the ddsim/k4run full simulation/reconstruction chain instead of FastSimSGV
    # (the default)
    simulation = EVENT_SIM_ENUM.FULL_DDSIM

    # k4run for LLR, Marlin for HLR and analysis
    low_level_reco = RECO_ANA_RUNMODES.K4RUN
    high_level_reco = RECO_ANA_RUNMODES.MARLIN
    analysis = RECO_ANA_RUNMODES.MARLIN

    compact_file = '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml'

    task_kwargs = {
        'DDSimBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ddsim_steer.py',
            'compact_file': compact_file,
        },
        'LowLevelRecoAbstract': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ILDReconstruction.py',
            'compact_file': compact_file,
            # arguments of the steering file (see LowLevelRecoAbstract)
            'constants': { 'lcioOutput': 'off', 'cmsEnergy': 250 },
        },
        # all stages use the same tasks, independent of Marlin or k4run being used; their
        # properties (steering file, ...) can be set for all ('RecoAnaBaseJob') or per stage
        'RecoAnaBaseJob': {
            'compact_file': compact_file,
        },
        'RecoAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/high_level_reco.py',
            'output_file': 'reco.edm4hep.root',
            'check_output_lcio_files': None,
        },
        'AnalysisAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/analysis_lepton_pairing.py',
            'output_file': 'analysis.edm4hep.root',
            'check_output_root_ttrees': None,
            # everything the steering file writes (here also a ROOT file with a TTree) is kept in the output directory
            'constants': { 'marlinDll': os.path.expandvars('$LEPTON_PAIRING_DLL') },
        },
    }

    whizard_options: list[WhizardOption] = [{
        'process_name': 'e2e2h',
        'process_definition': 'process e2e2h = e1,E1 => e2, E2, h { $omega_flags = "-model:constant_width" }',
        'template_dir': '$ANALYSIS_PATH/resources/whizard_template',
        'sindarin_file': 'whizard.base250.sin',
        # only eL.pR (beamPol1=-1, beamPol2=+1), one iteration - and no other polarization
        'iters_per_polarization': {
            'eL.pR': 1,
            'eR.pL': 1
        },
        'nevents': 100,
    }]


configurations.add(TestE500ZHFullK4RunConfig())
