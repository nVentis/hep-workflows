"""Building blocks shared by the test configurations"""

from typing import TYPE_CHECKING

from hep_workflows.framework import event_generation_output_files
from hep_workflows.utils.types import SGVOptions, WhizardOption

if TYPE_CHECKING:
    from hep_workflows.tasks_sim import FastSimSGV

# the compact file used by ddsim and k4run
COMPACT_FILE = '$K4GEO/ILD/compact/ILD_l5_o1_v02/ILD_l5_o1_v02.xml'

# e+e- -> mu+mu- h at 250 GeV; only each one file for the polarizations eL.pR and eR.pL.
# e2e2h is already defined in whizard.base250.sin; a process_definition may only add processes with other names
def E250_ZH_WHIZARD_OPTIONS(nevents:int=100)->list[WhizardOption]:
    return [{
        'process_name': 'e2e2h',
        'process_definition': '',
        'template_dir': '$ANALYSIS_PATH/resources/whizard_template',
        'sindarin_file': 'whizard.base250.sin',
        'iters_per_polarization': {
            'eL.pR': 1,
            'eR.pL': 1
        },
        'nevents': nevents
    }]

def whizard_to_sgv_inputs(sqrt_s:float, task:'FastSimSGV')->tuple[list[str], list[SGVOptions]]:
    """FastSimSGV input: all files produced by WhizardEventGeneration, which the task requires.
    Use it in `AnalysisConfiguration.sgv_inputs(self, task)`."""
    input_files = event_generation_output_files(task)

    return input_files, [{
        'global_steering.MAXEV': 999999,
        'global_generation_steering.CMS_ENE': sqrt_s,
        'external_read_generation_steering.GENERATOR_INPUT_TYPE': 'LCIO',
        'external_read_generation_steering.INPUT_FILENAMES': 'input.slcio',
        'analysis_steering.CALO_TREATMENT': 'PERF'
    }] * len(input_files)
