"""Minimal end-to-end configuration exercising the full-simulation chain with Gaudi/k4run based
reconstruction and analysis (low_level_reco = high_level_reco = analysis = RECO_ANA_RUNMODES.K4RUN) at 500 GeV:

WhizardEventGeneration -> GeneratorIndex -> DDSim[Runtime, Chunks, Final] ->
LowLevelRecoIndex -> LowLevelRecoRuntime -> CreateLowLevelRecoChunks ->
LowLevelRecoFinal -> RawIndex -> Reco[Runtime, CreateChunks, Final] ->
AnalysisIndex -> Analysis[Runtime, CreateChunks, Final]

A copy of TestE500ZHFullConfig (test_e500_zh_full.py), with only 100 events generated so the
whole chain can be run as a short validation. The high-level reconstruction (FastJet, isolated
lepton and photon ID) and the analysis (isolated lepton pairing only) use the example steering
files in resources/k4run. The LeptonPairing processor is part of the ZHH repository, not of the
key4hep stack, and has to be compiled against the key4hep (nightly) stack in use; set
$LEPTON_PAIRING_DLL to the resulting library, e.g. in the .env file.

This file only registers an AnalysisConfiguration and does not define any
task classes itself, so `law run <Task> --tag=...` won't discover it
automatically (law only imports the module that defines the requested task).
Run tasks against this config with an explicit --module, e.g.:

    law run AnalysisFinal --tag=500-e2e2h-ild-full-k4run --module hep_workflows.tests.test_e500_zh_full_k4run
"""

import os

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.utils.types import WhizardOption


class TestE500ZHFullK4RunConfig(AnalysisConfiguration):
    tag = '500-e2e2h-ild-full-k4run'
    sqrt_s = 500.

    # use the ddsim/k4run full simulation/reconstruction chain instead of FastSimSGV
    # (the default)
    simulation = EVENT_SIM_ENUM.FULL_DDSIM

    # k4run for all stages: the low-level reconstruction after ddsim (the default for full_ddsim),
    # the high-level reconstruction and the analysis (instead of Marlin)
    low_level_reco = RECO_ANA_RUNMODES.K4RUN
    high_level_reco = RECO_ANA_RUNMODES.K4RUN
    analysis = RECO_ANA_RUNMODES.K4RUN

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
            'constants': { 'lcioOutput': 'off', 'cmsEnergy': 500 },
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
        'sindarin_file': 'whizard.base500.sin',
        # only eL.pR (beamPol1=-1, beamPol2=+1), one iteration - and no other polarization
        'iters_per_polarization': {'eL.pR': 1},
        'nevents': 100,
    }]


configurations.add(TestE500ZHFullK4RunConfig())
