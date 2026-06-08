from abc import abstractmethod
from typing import cast
from tasks.tasks_generator import WhizardEventGeneration
from tasks.tasks_sim import FastSimSGV
import subprocess
import law
from law.util import flatten
import os.path as osp

class TestGeneratorE550bbbb(WhizardEventGeneration):
    def create_branch_map(self) -> dict[int, dict]:
        branch_map = {}

        whiz_ver = subprocess.check_output([f'source "{self.env_script}" && echo $(which whizard) && whizard --version'], shell=True).split()[1].decode('utf-8')
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
                nbranch += 1

                branch_map[nbranch] = branch_value

        return branch_map
    
    def complete(self):
        compl = super().complete()
        print(f'complete == {self.complete}')

        return compl


class TestSGVE550bbbb(FastSimSGV):
    def workflow_requires(self):
        requirements = super(TestSGVE550bbbb, self).workflow_requires()
        requirements['whizard_event_generation'] = TestGeneratorE550bbbb.req(self)
        
        return requirements
    
    def sgv_inputs(self):
        print(self)

        sgv_inputs = self.input()
        assert('whizard_event_generation' in sgv_inputs)
        
        whiz_outputs = sgv_inputs['whizard_event_generation']['collection']
        print(whiz_outputs)
        print(len(whiz_outputs))
        
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
    
    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))
        
    @workflow_condition.create_branch_map
    def create_branch_map(self):
        input_files, input_options = self.sgv_inputs()
        assert(len(input_files) == len(input_options))
        
        bmap = { k: [file, options] for (k, file, options) in zip(
            list(range(len(input_files))),
            input_files,
            input_options
        )}

        print('branch_map', bmap)
        return bmap
    
    @workflow_condition.output
    def output(self):
        # output filename = input filename but extension changed to 'slcio'; necessary for stdhep input
        return self.local_target(f'{osp.splitext(osp.basename(self.branch_data[0]))[0]}.slcio')