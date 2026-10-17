"""Minimal end-to-end configuration exercising the full-simulation chain with Gaudi/k4run based
reconstruction and analysis (analysis = EVENT_ANALYSIS_ENUM.K4RUN) at 500 GeV:

WhizardEventGeneration -> GeneratorIndex -> DDSim[Runtime, Chunks, Final] ->
K4RunLowLevelRecoIndex -> K4RunLowLevelRecoRuntime -> K4RunLowLevelRecoCreateChunks ->
K4RunLowLevelRecoFinal -> RawIndex -> K4RunHighLevelReco[Runtime, CreateChunks, Final] ->
AnalysisIndex -> K4RunAnalysis[Runtime, CreateChunks, Final]

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

    law run K4RunAnalysisFinal --tag=500-e2e2h-ild-full-k4run --module hep_workflows.tests.test_e500_zh_full_k4run
"""

import os

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, EVENT_ANALYSIS_ENUM
from hep_workflows.utils.types import WhizardOption


class TestE500ZHFullK4RunConfig(AnalysisConfiguration):
    tag = '500-e2e2h-ild-full-k4run'
    sqrt_s = 500.

    # use the ddsim/k4run full simulation/reconstruction chain instead of FastSimSGV
    # (the default)
    simulation = EVENT_SIM_ENUM.FULL_DDSIM

    # use Gaudi/k4run for the high-level reconstruction and the analysis instead of Marlin
    analysis = EVENT_ANALYSIS_ENUM.K4RUN

    compact_file = '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml'

    task_kwargs = {
        'DDSimBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ddsim_steer.py',
            'compact_file': compact_file,
        },
        'K4RunLowLevelRecoBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ILDReconstruction.py',
            'compact_file': compact_file,
        },
        'K4RunHighLevelRecoBaseJob': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/high_level_reco.py',
            'compact_file': compact_file,
        },
        'K4RunAnalysisBaseJob': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/analysis_lepton_pairing.py',
            'compact_file': compact_file,
            'k4run_arguments': { 'marlinDll': os.path.expandvars('$LEPTON_PAIRING_DLL'), 'rootFile': 'LeptonPairing.root' },
            # the TTree of the LeptonPairing processor is kept as <output name>.LeptonPairing.root
            'extra_output_files': ['LeptonPairing.root'],
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
