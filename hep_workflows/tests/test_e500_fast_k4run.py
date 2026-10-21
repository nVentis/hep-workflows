"""Minimal configuration exercising Gaudi/k4run based high-level reconstruction and analysis
(high_level_reco = analysis = RECO_ANA_RUNMODES.K4RUN) on samples of the fast simulation (SGV)
at 550 GeV: RawIndex -> Reco[Runtime, CreateChunks, Final] -> AnalysisIndex -> Analysis[Runtime, CreateChunks, Final]

SGV directly produces reconstructed particles (LCIO), i.e. the low-level reconstruction is skipped
(low_level_reco is forced to None for simulation = fast_sgv). Here, two existing output files of
FastSimSGV are used as input; k4run reads them via LcioEvent and writes edm4hep. 

The steering files are the examples in resources/k4run. The LeptonPairing processor is part of the
ZHH repository, not of the key4hep stack, and has to be compiled against the key4hep (nightly)
stack in use; set $LEPTON_PAIRING_DLL to the resulting library, e.g. in the .env file.

This file only registers an AnalysisConfiguration and does not define any
task classes itself, so `law run <Task> --tag=...` won't discover it
automatically (law only imports the module that defines the requested task).
Run tasks against this config with an explicit --module, e.g.:

    law run AnalysisFinal --tag=550-zh-fast-k4run --module hep_workflows.tests.test_e500_fast_k4run
"""

import os

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES


class TestE550ZHFastK4RunConfig(AnalysisConfiguration):
    tag = '550-zh-fast-k4run'
    sqrt_s = 550.

    simulation = EVENT_SIM_ENUM.FAST_SGV

    high_level_reco = RECO_ANA_RUNMODES.K4RUN
    analysis = RECO_ANA_RUNMODES.K4RUN

    # existing output files of FastSimSGV; set $SGV_SAMPLE_DIR to the directory containing them
    slcio_files = [
        '$SGV_SAMPLE_DIR/E550_TDR.Pzh_bbh.Gwhizard-3.1.4.eL.pL.0.slcio',
        '$SGV_SAMPLE_DIR/E550_TDR.Pzh_cch.Gwhizard-3.1.4.eL.pL.0.slcio',
    ]

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
        },
        'AnalysisAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/analysis_lepton_pairing.py',
            'output_file': 'analysis.edm4hep.root',
            'check_output_root_ttrees': None,
            'constants': { 'marlinDll': os.path.expandvars('$LEPTON_PAIRING_DLL') },
        },
    }

    def __init__(self):
        super().__init__()

        self.slcio_files = [os.path.expandvars(f) for f in self.slcio_files]


configurations.add(TestE550ZHFastK4RunConfig())
