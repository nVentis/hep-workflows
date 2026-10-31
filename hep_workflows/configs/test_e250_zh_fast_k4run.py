"""Minimal end-to-end configuration exercising the fast-simulation chain with Gaudi/k4run based
high-level reconstruction: WhizardEventGeneration -> GeneratorIndex -> FastSimSGV -> RawIndex ->
RecoRuntime -> CreateRecoChunks -> RecoFinal. The analysis stage is not covered.

SGV directly produces reconstructed particles (LCIO), i.e. the low-level reconstruction is skipped.
k4run reads them via LcioEvent and writes edm4hep. The steering file is the example in resources/k4run.

    law run RecoFinal --tag=250-e2e2h-ild-fast-k4run --module hep_workflows.configs.test_e250_zh_fast_k4run
"""

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.configs.common import COMPACT_FILE, E250_ZH_WHIZARD_OPTIONS, whizard_to_sgv_inputs


class TestE250ZHFastK4RunConfig(AnalysisConfiguration):
    tag = '250-e2e2h-ild-fast-k4run'
    sqrt_s = 250.

    simulation = EVENT_SIM_ENUM.FAST_SGV

    high_level_reco = RECO_ANA_RUNMODES.K4RUN
    analysis = RECO_ANA_RUNMODES.K4RUN

    task_kwargs = {
        # sets the property 'compact_file' on all classes inheriting from RecoAnaBaseJob
        # i.e. also for Reco* tasks (high-level reconstruction)
        'RecoAnaBaseJob': {
            'compact_file': COMPACT_FILE,
        },

        # HighLevelReco (so far just 'Reco') uses k4run, as specified above
        'RecoAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/high_level_reco.py',
            'output_file': 'reco.edm4hep.root',
            'check_output_lcio_files': None,
            # cap the number of events if not given by the chunk plan, i.e. for RecoRuntime
            'n_events_max': 50,
        }
    }

    whizard_options = E250_ZH_WHIZARD_OPTIONS(nevents=100)

    def sgv_inputs(self, task):
        return whizard_to_sgv_inputs(self.sqrt_s, task)

    def setup(self):
        from .provisioning import provision_sgv, provision_ild_config

        # the isolated lepton weights of high_level_reco.py are taken from ILDConfig
        provision_ild_config()
        provision_sgv()


configurations.add(TestE250ZHFastK4RunConfig())
