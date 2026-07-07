from typing import cast
import subprocess

from hep_workflows.tasks_generator import WhizardEventGeneration
from hep_workflows.tasks_sim import AbstractSGVExternalReadJob, FastSimSGV
from hep_workflows.tasks_index import AbstractIndex
from hep_workflows.utils.tasks import BaseTask
from hep_workflows.framework import HTCondorWorkflow
import law

class TestBatchEnvironmentE550bbbb(BaseTask):
    def output(self):
        return self.local_target('env.txt')
    
    def run(self):
        subprocess.check_output([f'mkdir -p "{self.output().absdirname}" && set > "{self.output().abspath}"'], shell=True)

class TestExampleWorkflow(BaseTask, HTCondorWorkflow):
    def create_branch_map(self):
        branch_map = {}

        for i in range(10):
            branch_map[i] = ( i, 'some_other_argument' )
        
        return branch_map

    def output(self):
        return self.local_target(f'{self.branch}.txt')
    
    def computation(self, value):
        return value ** 2

    def run(self):
        i, arg = cast(tuple, self.branch_data)
        
        target = self.output()
        parent = cast(law.LocalDirectoryTarget, target.parent)
        parent.touch()

        with open(cast(str, target.abspath), 'w') as file:
            file.write(f'computation({i}) = {self.computation(i)}; arg = {arg}')

class TestGeneratorE550bbbb(WhizardEventGeneration):
    """This class represents a workflow for generating bbbb events at 550 GeV COM energy using ILC beam spectrum
    The base functionality is provided by the WhizardEventGeneration class. Here, create_branch_map is overwritten
    to define "by-hand" that for each polarization combination, there should be 10 runs with 10.000 events each.
    The Sindarin file and a few other options are specified as well. Note that the COM_ENERGY is hard-coded in the
    Sindarin files and only used here to get the naming right.

    Args:
        WhizardEventGeneration (_type_): _description_
    """

    def create_branch_map(self) -> dict[int, dict]:
        branch_map = {}

        whiz_ver = subprocess.check_output([f'echo $(which whizard) && whizard --version'], shell=True).split()[1].decode('utf-8')
        nbranch = 0

        for beamPol1, beamPol2, pol_key in [
                ('-1', '-1', 'eL.pL'),
                ('-1',  '1', 'eL.pR'),
                ( '1', '-1', 'eR.pL'),
                ( '1',  '1', 'eR.pR')
            ]:
            for i in range(10):
                # in SINDARIN_FILE, each $<PROP> will be replaced with branch_value[PROP] 
                branch_value = {
                    'COM_ENERGY': 550,
                    'WHIZARD_VERSION': whiz_ver,
                    'POLARIZATION_KEY': pol_key,
                    'BEAMPOL1': beamPol1,
                    'BEAMPOL2': beamPol2,
                    'PROCESS_NAME': 'bbbb_sl0',
                    'TEMPLATE_DIR': '$ANALYSIS_PATH/resources/whizard_template',
                    'SINDARIN_FILE': 'whizard.base550.sin',
                    'OUTPUT_INDEX': i,
                    'NEVENTS': 10000
                }

                branch_map[nbranch] = branch_value
                nbranch += 1

        return branch_map

class TestSGVE550bbbb(FastSimSGV):
    """This workflow runs fast simulation using SGV for each file produced by the TestGeneratorE550bbbb task

    Args:
        FastSimSGV (_type_): _description_
    """
    def workflow_requires(self):
        requirements = super(AbstractSGVExternalReadJob, self).workflow_requires()
        requirements['whizard_event_generation'] = TestGeneratorE550bbbb.req(self)
        
        return requirements

    def sgv_inputs(self):
        inputs = self.input()
        assert('whizard_event_generation' in inputs)
        
        whiz_outputs = inputs['whizard_event_generation']['collection']
        input_files:list[str] = []
        for i in range(len(whiz_outputs)):
            input_files.append(whiz_outputs[i][0].path)
        
        input_options = [{
            'global_steering.MAXEV': 999999,
            'global_generation_steering.CMS_ENE': 550,
            'external_read_generation_steering.GENERATOR_INPUT_TYPE': 'LCIO',
            'external_read_generation_steering.INPUT_FILENAMES': 'input.slcio',
            'analysis_steering.CALO_TREATMENT': 'PERF'
        }] * len(input_files)
        
        return input_files, input_options

class TestIndex550bbbb(AbstractIndex):
    """This task creates an index of all samples and encountered physics processes including their cross-section
    by reading the relevant information using pyLCIO (see the ProcessIndex class used in AbstractIndex).

    Args:
        AbstractIndex (_type_): _description_
    """
    def requires(self):
        reqs = {}
        reqs['sgv_task'] = TestSGVE550bbbb.req(self)
        
        return reqs

    def slcio_files(self)->list[str]:
        inputs = self.input()
        assert('sgv_task' in inputs and 'collection' in inputs['sgv_task'])
        
        collection = inputs['sgv_task']['collection']

        return [ collection[i].path for i in range(len(collection)) ]