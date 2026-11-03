"""Minimal end-to-end configuration exercising the full-simulation chain with Gaudi/k4run based
low-level and high-level reconstruction: WhizardEventGeneration -> GeneratorIndex -> DDSimRuntime ->
CreateDDSimChunks -> DDSimFinal -> LowLevelRecoIndex -> LowLevelRecoRuntime -> CreateLowLevelRecoChunks ->
LowLevelRecoFinal -> RawIndex -> RecoRuntime -> CreateRecoChunks -> RecoFinal. The analysis stage is not covered.

Full simulation is validated against key4hep NIGHTLY builds (set $K4H_NIGHTLY). Marlin cannot read
the edm4hep output of the low-level reconstruction, so there is no full-simulation configuration
with a Marlin based high-level reconstruction.

    law run RecoFinal --tag=250-e2e2h-ild-full-k4run --module hep_workflows.configs.test_e250_zh_full_k4run
"""

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM, RECO_ANA_RUNMODES
from hep_workflows.configs.common import COMPACT_FILE, E250_ZH_WHIZARD_OPTIONS


class TestE250ZHFullK4RunConfig(AnalysisConfiguration):
    tag = '250-e2e2h-ild-full-k4run'
    sqrt_s = 250.

    simulation = EVENT_SIM_ENUM.FULL_DDSIM

    # k4run for all stages
    low_level_reco = RECO_ANA_RUNMODES.K4RUN
    high_level_reco = RECO_ANA_RUNMODES.K4RUN
    analysis = RECO_ANA_RUNMODES.K4RUN

    task_kwargs = {
        'DDSimBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ddsim_steer.py',
            'compact_file': COMPACT_FILE,
        },

        # LowLevelReco uses k4run, as specified above
        'LowLevelRecoAbstract': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ILDReconstruction.py',

            # arguments of the steering file (see LowLevelRecoAbstract)
            'constants': {
                'lcioOutput': 'off',
                'cmsEnergy': 250
            },
        },

        # sets the property 'compact_file' on all classes inheriting from RecoAnaBaseJob
        # i.e. also on LowLevelRecoAbstract
        'RecoAnaBaseJob': {
            'compact_file': COMPACT_FILE,
        },

        # HighLevelReco (so far just 'Reco') uses k4run, as specified above
        'RecoAbstract': {
            'steering_file': '$ANALYSIS_PATH/resources/k4run/high_level_reco.py',
            'output_file': 'reco.edm4hep.root',
            'check_output_lcio_files': None,
        }
    }

    whizard_options = E250_ZH_WHIZARD_OPTIONS(nevents=30)

    def setup(self):
        from .provisioning import provision_ild_config

        provision_ild_config()


configurations.add(TestE250ZHFullK4RunConfig())
