"""Minimal end-to-end configuration exercising the full-simulation/reconstruction
chain (see tasks_sim_full.py) at 500 GeV: WhizardEventGeneration -> RawIndex ->
DDSimRuntime -> CreateDDSimChunks -> DDSimFinal -> K4RunIndex ->
K4RunRuntime -> CreateK4RunChunks -> K4RunFinal.

Only the eL.pR polarization is generated (10 events), keeping the sample small
enough to run through the whole chain quickly. whizard.base500.sin already
defines Zh-associated processes at the correct 500 GeV COM energy (unlike
whizard.base550.sin's bbbb_sl0, which hardcodes sqrts=550 internally), so no
new sindarin template is needed here.

DDSimBaseJob/K4RunBaseJob's steering_file/compact_file are obligatory (see
AbstractDDSim/AbstractK4Run in tasks_sim_full.py) - task_kwargs below sets both
on each to exercise ILD_l5_o1_v02, one of the regular (non-FCCee) ILD models,
which k4geo lays out under ILD/compact/ rather than FCCee/ILD_FCCee/compact/.
Reconstruction runs ILDConfig's own ILDReconstruction.py (via K4RunBaseJob's
steering_file).

Integration with the subsequent RecoRuntime/RecoFinal and AnalysisRuntime/
AnalysisFinal (Marlin) tasks is intentionally not covered yet: those don't
support ddsim/k4run's edm4hep output until a Gaudi-based equivalent exists
(see the "Known upstream issue" note in the README) - independent of which
detector model is used above.

This file only registers an AnalysisConfiguration and does not define any
task classes itself, so `law run <Task> --tag=...` won't discover it
automatically (law only imports the module that defines the requested task).
Run tasks against this config with an explicit --module, e.g.:

    law run WhizardEventGeneration --tag=e500_zh_full --module hep_workflows.tests.test_e500_zh_full
    law run DDSimFinal --tag=e500_zh_full --module hep_workflows.tests.test_e500_zh_full
    law run K4RunFinal --tag=e500_zh_full --module hep_workflows.tests.test_e500_zh_full
"""

from hep_workflows.framework import AnalysisConfiguration, configurations, EVENT_SIM_ENUM
from hep_workflows.utils.types import WhizardOption


class TestE500ZHFullConfig(AnalysisConfiguration):
    tag = '500-e2e2h-ild-full'
    sqrt_s = 500.

    # use the ddsim/k4run full simulation/reconstruction chain instead of FastSimSGV
    # (the default)
    simulation = EVENT_SIM_ENUM.FULL_DDSIM

    # steering_file/compact_file are obligatory (no built-in default - see AbstractDDSim/
    # AbstractK4Run in tasks_sim_full.py), and target a regular (non-FCCee) ILD model here:
    # k4geo lays out ILD_l5_o1_v02 under ILD/compact/, not FCCee/ILD_FCCee/compact/
    task_kwargs = {
        'DDSimBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ddsim_steer.py',
            'compact_file': '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml',
        },
        'K4RunBaseJob': {
            'steering_file': '$ILD_CONFIG_DIR/StandardConfig/production/ILDReconstruction.py',
            'compact_file': '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml',
        },
    }

    whizard_options: list[WhizardOption] = [{
        # process_name must match the process declared (built-in or via process_definition
        # below) that ends up in the generated .sin file's `simulate ($PROCESS_NAME)` line
        'process_name': 'e2e2h',
        # inserted verbatim into the sindarin file (see $PROCESS_DEFINITION in
        # whizard.base500.sin); must use a name distinct from the template's built-in
        # processes (zh_e3e3nunu/zh_ddh/zh_uuh/zh_ssh/zh_cch/zh_bbh) to avoid Whizard's
        # "process has already been defined" error
        'process_definition': 'process e2e2h = e1,E1 => e2, E2, h { $omega_flags = "-model:constant_width" }',
        'template_dir': '$ANALYSIS_PATH/resources/whizard_template',
        'sindarin_file': 'whizard.base500.sin',
        # only eL.pR (beamPol1=-1, beamPol2=+1), one iteration - and no other polarization
        'iters_per_polarization': {'eL.pR': 1},
        'nevents': 100_000,
    }]


configurations.add(TestE500ZHFullConfig())
