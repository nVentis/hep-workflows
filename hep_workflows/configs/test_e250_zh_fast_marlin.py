"""Minimal end-to-end configuration exercising the fast-simulation chain with Marlin based
high-level reconstruction: WhizardEventGeneration -> GeneratorIndex -> FastSimSGV -> RawIndex ->
RecoRuntime -> CreateRecoChunks -> RecoFinal. The analysis stage is not covered.

SGV directly produces reconstructed particles (LCIO), i.e. the low-level reconstruction is skipped.
The Marlin steering file is the example in resources/marlin.

    law run RecoFinal --tag=250-e2e2h-ild-fast-marlin --module hep_workflows.configs.test_e250_zh_fast_marlin
"""

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.configs.common import E250_ZH_WHIZARD_OPTIONS, whizard_to_sgv_inputs


class TestE250ZHFastMarlinConfig(AnalysisConfiguration):
    tag = '250-e2e2h-ild-fast-marlin'
    sqrt_s = 250.

    simulation = EVENT_SIM_ENUM.FAST_SGV

    high_level_reco = RECO_ANA_RUNMODES.MARLIN
    analysis = RECO_ANA_RUNMODES.MARLIN

    task_kwargs = {
        # HighLevelReco (so far just 'Reco') uses Marlin, as specified above
        'RecoAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/marlin/high_level_reco.xml',
            'output_file': 'reco.slcio',
            'check_output_lcio_files': ['reco.slcio'],
            # cap the number of events if not given by the chunk plan, i.e. for RecoRuntime
            'n_events_max': 50,
        }
    }

    whizard_options = E250_ZH_WHIZARD_OPTIONS(nevents=100)

    def sgv_inputs(self, task):
        return whizard_to_sgv_inputs(self.sqrt_s, task)

    def setup(self):
        from .provisioning import provision_sgv

        provision_sgv()


configurations.add(TestE250ZHFastMarlinConfig())
