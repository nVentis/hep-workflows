from typing import cast
from collections.abc import Callable
from abc import ABC, abstractmethod
import os.path as osp

from .framework import HTCondorWorkflow, configurations
from .utils import ShellTask
from .utils.types import MarlinBranchValue, MarlinSteeringDict
from law.util import flatten
import numpy as np
import law

class AbstractMarlin(ABC, ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    """Abstract class for Marlin jobs
    
    The parameters for running Marlin can be set here
    or overwritten in a child class by a custom imple-
    mentation of get_steering_parameters.
    
    Considers two targets per task branch:
    - output[0]: a directory, identified as the temp.
        working directory in which Marlin is run
    - output[1]: a file, identified by self.output_file
    """
    
    executable = 'Marlin'
    steering_file:str = 'steer.xml' # change this to your favorite steering file and make sure it's accessible (e.g. findable from an environment variable)

    # file to be moved to the file output location (output[1])
    output_file:str = 'AIDA.root'
    
    n_events_max:int|None = None
    n_events_skip:int|None = None
    
    # Append to these of you want to set additional constants or globals
    # You may define a pre_run_command to do so in a dynamic way 
    constants:dict[str,str] = {}
    globals:dict[str,str] = {}
    
    # Optional: list of tuples of structure (file-name.root, TTree-name)
    check_output_root_ttrees:list[tuple[str,str]]|None = None 
    
    # Optional: list of files
    check_output_files_exist:list[str]|None = None
    
    # Optional: list of SLCIO files for which lcio_event_counter
    # must return successfully a number > 0
    check_output_lcio_files:list[str]|None = None
    
    @abstractmethod
    def get_steering_parameters(self)->MarlinSteeringDict:
        pass
    
    def get_temp_dir(self):
        return f'{self.htcondor_output_directory().path}/TMP-{self.output_name()}'
    
    def output_name(self):
        branch_data = cast(MarlinBranchValue, self.branch_data)
        input_file = branch_data[0]
        output_bname = branch_data[-1]
        
        if isinstance(input_file, str):
            sample_filename = osp.basename(input_file)
            n_chunk = branch_data[1]
            n_chunks_in_sample = branch_data[2]
            
            return f'{osp.splitext(sample_filename)[0]}.{n_chunk}-{n_chunks_in_sample}-{str(self.branch)}'
        elif isinstance(input_file, list) and isinstance(output_bname, str):
            return f'{output_bname}-{str(self.branch)}.slcio'
        else:
            raise Exception('Either input_file must be a string, or a list while output_bname is a str')
    
    def parse_marlin_globals(self) -> str:
        globals = filter(lambda tup: tup[0] not in ['MaxRecordNumber', 'LCIOInputFiles', 'SkipNEvents'], self.globals)
        return ' '.join([f'--global.{key}="{value}"' for key, value in globals])
    
    def parse_marlin_constants(self) -> str:
        return ' '.join([f'--constant.{key}="{value}"' for key, value in self.constants])
    
    def build_command(self, **kwargs):
        steering = self.get_steering_parameters()
        
        input_files = steering['input_files']
        n_events_skip = steering['n_events_skip']
        n_events_max = steering['n_events_max']
        executable = steering['executable']
        steering_file = steering['steering_file']
        
        temp = self.get_temp_dir()
        
        cmd =  f'source $ANALYSIS_PATH/setup_batch.sh'
        cmd += f' && echo "Starting Marlin at $(date)"'
        cmd += f' && rm -rf {self.htcondor_output_directory().path}/*-{str(self.branch)}'
        cmd += f' && mkdir -p "{temp}" && cd "{temp}"'
        
        str_max_record_number = f' --global.MaxRecordNumber={str(n_events_max + 1 if (n_events_max > 0 and n_events_skip is not None and n_events_skip > 0) else n_events_max)}' if n_events_max is not None else ''
        str_skip_n_events = f' --global.SkipNEvents={str(n_events_skip)}' if (n_events_skip is not None and n_events_skip > 0) else ''
        
        cmd += f' && ( {executable} {steering_file} {self.parse_marlin_constants()}{self.parse_marlin_globals()}{str_max_record_number}{str_skip_n_events} --global.LCIOInputFiles="{" ".join(input_files)}" || true )'
        cmd += f' && echo "{",".join(input_files)}" >> Source.txt'
        cmd += f' && echo "Finished Marlin at $(date)"'
        cmd += f' && ( sleep 2'
        
        if self.check_output_root_ttrees is not None:
            for name, ttree in self.check_output_root_ttrees:
                cmd += f' && ( echo "Info: Checking if TTree <{ttree}> exists" && is_root_readable ./{name} {ttree} && echo "Success: TTree <{ttree}> in file <{name}> exists" ) '
                
        if self.check_output_files_exist is not None:
            for name in self.check_output_files_exist:
                cmd += f' && echo "Info: Checking if file <{name}> exists" && [ -f ./{name} ] && echo "Success: File <{name}> exists"'
        
        if self.check_output_lcio_files is not None:
            for name in self.check_output_lcio_files:
                cmd += f' && echo "Info: Checking with lcio_event_counter that file <{name}> contains events" && counts=$(lcio_event_counter {name}) && [ ! -z "$counts" ] && [ "$counts" -gt 0 ] && echo "Success: File <{name}> contains <${{counts}}> events!"'
        
        cmd += f' && mv "{self.output_file}" "{self.output()[1].path}" && cd .. && mv "{temp}" "{self.output()[0].path}" )'

        return cmd
    
    def output(self):
        return [
            self.local_directory_target(str(self.branch)),
            self.local_target(f'{self.branch}.slcio')
        ]
        
    def run(self, **kwargs):
        ShellTask.run(self, keep_cwd=True, **kwargs)


class MarlinBaseJob(AbstractMarlin):
    """Base class for Marlin jobs. Tasks subclassing this must imple-
    ment/define correctly:
    - output_file (see documentation of AbstractMarlin)
    - workflow_requires() and requires(), which are expected to return:
        - 'index_task': task subclassing AbstractIndex
        - 'marlin_chunks': task subclassing AbstractCreateChunks, only
            required if self.debug is False (as is for
            [Analysis/Reco]Final tasks)

    Args:
        AbstractMarlin (_type_): _description_

    Returns:
        _type_: _description_
    """
    debug = True
    
    # controls how many files are processed in debug mode (e.g. AnalysisRuntime). if None, all files are processed
    debug_n_files_to_process:int|None = 3
    
    constants = {
        'ILDConfigDir': '$ILD_CONFIG_DIR', # read from environment variable
        'OutputDirectory': '.'
    }
    
    # Attach MCParticleCollectionName and constants/globals for Marlin
    def pre_run_command(self, **kwargs):
        config = configurations.get(str(self.tag))
        
        if 'MarlinBaseJob' in config.task_kwargs:
            for prop, value in config.task_kwargs['MarlinBaseJob'].items():
                setattr(self, prop, value)
 
        mcp_col_name:str = self.get_steering_parameters()['mcp_col_name']
        
        self.constants['MCParticleCollectionName'] = mcp_col_name
        
        marlin_constants = config.marlin_constants(self.branch, self.branch_data) if isinstance(config.marlin_constants, Callable) else config.marlin_constants
        for key, value in marlin_constants.items():
            self.constants[key] = str(value)
        
        for key, value in config.marlin_globals.items():
            self.globals[key] = str(value)
    
    @law.dynamic_workflow_condition
    def workflow_condition(self):
        # declare that the branch map can be built only if the workflow requirement exists
        # the decorator will trigger a run of workflow_requires beforehand
        # because of the decorator, self.input() will refer to the outputs of tasks defined in workflow_requires()
        
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))
    
    # The decorator @workflow_condition.create_branch_map is required
    # for all workflows which require a branch map conditioned on the
    # output of a previous task (in this case, RawIndex)
    @workflow_condition.create_branch_map
    def create_branch_map(self) -> dict[int, MarlinBranchValue]:
        branch_map:dict[int, MarlinBranchValue] = {}
        
        config = configurations.get(str(self.tag))
        if 'MarlinBaseJob' in config.task_kwargs:
            for prop, value in config.task_kwargs['MarlinBaseJob'].items():
                setattr(self, prop, value)
        
        samples = np.load(self.input()['index_task'][1].path)
        
        if not self.debug:
            
            # The calculated chunking is used
            chunks = np.load(self.input()['marlin_chunks'][0].path)
            
            if 'sub_branch_size' in chunks.dtype.names:
                filecount = {}
                
                for branch in np.unique(chunks['branch']).tolist():
                    c_chunks = chunks[chunks['branch'] == branch]
                    src_bname = c_chunks['src_bname'][0]
                    files = list(c_chunks['location'])
                    
                    if src_bname not in filecount:
                        filecount[src_bname] = 0
                    else:
                        filecount[src_bname] += 1
                    
                    branch_map[branch] = (
                        files,
                        0,
                        0,
                        None,
                        0,
                        samples['mcp_col_name'][samples['location'] == files[0]][0], # require mcp_col_name to be equal
                        f'{src_bname}.{filecount[src_bname]}'
                    )
                    
            else:
                mcp_col_name = samples['mcp_col_name'][0]
                mcp_col_identical = np.all(samples['mcp_col_name'] == mcp_col_name)

                for branch in chunks['branch'].tolist():
                    if not mcp_col_identical:
                        # find mcp collection name per file
                        assert(np.sum(samples['location'] == chunks['location'][branch]))
                        mcp_col_name = samples['mcp_col_name'][samples['location'] == chunks['location'][branch]][0]

                    branch_map[branch] = (
                        chunks['location'][branch],
                        chunks['n_chunk_in_sample'][branch],
                        chunks['n_chunks_in_sample'][branch],
                        chunks['chunk_start'][branch],
                        chunks['chunk_size'][branch],
                        mcp_col_name,
                        None
                    )
                
            #branch_map = { k: v for k, v in zip(
            #    scs['branch'].tolist(),
            #    zip(scs['location'],
            #        scs['chunk_start'],
            #        scs['chunk_size'],
            #        samples['mcp_col_name'][scs['sid']])) }
        else:
            
            # A debug run. The default settings
            # from the steering file are used
            selection = samples[np.lexsort((samples['location'], samples['proc_pol']))]
            
            i = 0
            
            for proc_pol in np.unique(selection['proc_pol']):
                items = selection[selection['proc_pol'] == proc_pol]
                if self.debug_n_files_to_process is not None and self.debug_n_files_to_process > 0:
                    items = items[:self.debug_n_files_to_process]
                
                for entry in items:
                    branch_map[i] = (
                        entry['location'],
                        0,
                        1,
                        -1,
                        -1,
                        entry['mcp_col_name'],
                        None
                    )
                    i += 1
        
        return branch_map

    @workflow_condition.output
    def output(self):
        output_name = self.output_name()
        assert('.' in self.output_file)
        
        return [
            self.local_directory_target(output_name),
            self.local_target(f'{output_name}.{self.output_file.split(".")[-1]}')
        ]

class RecoAbstract(MarlinBaseJob):
    steering_file:str = '$MARLIN_RECO_STEERING_FILE' # 'REPO_ROOT/scripts/prod_reco_run.xml'
    output_file:str = 'reco.slcio'
    
    check_output_files_exist = ['reco_FinalStateMeta.json']
    check_output_root_ttrees = None
    check_output_lcio_files = ['reco.slcio']
    
    def workflow_requires(self):
        from .tasks_index import RawIndex
        from .tasks_marlin_chunks import CreateRecoChunks
        
        reqs = {}
        reqs['index_task'] = RawIndex.req(self)
        
        if not self.debug:
            reqs['marlin_chunks'] = CreateRecoChunks.req(self)
        
        return reqs

class AnalysisAbstract(MarlinBaseJob):
    steering_file:str = '$MARLIN_ANALYSIS_STEERING_FILE' # 'REPO_ROOT/scripts/prod_analysis_run.xml'
    output_file:str = 'AIDA.root'
    
    check_output_files_exist = ['FinalStateMeta.json']
    check_output_root_ttrees = [
        ('AIDA.root', 'FinalStates'),
    ]
    
    def workflow_requires(self):
        from .tasks_index import AnalysisIndex
        from .tasks_marlin_chunks import CreateAnalysisChunks
        
        reqs = {}
        reqs['index_task'] = AnalysisIndex.req(self)
        
        if not self.debug:
            reqs['marlin_chunks'] = CreateAnalysisChunks.req(self)
        
        return reqs

class RecoRuntime(RecoAbstract):
    """Runs prod_reco_run.xml for a runtime analysis for each proc_pol combination
    """
    debug = True

class RecoFinal(RecoAbstract):
    """Runs prod_reco_run.xml for the full analysis for each proc_pol combination

    Args:
        AnalysisAbstract (_type_): _description_
    """
    debug = False

class AnalysisRuntime(AnalysisAbstract):
    """Runs prod_analysis_run.xml for a runtime analysis for each proc_pol combination
    """
    debug = True

class AnalysisFinal(AnalysisAbstract):
    """Runs prod_analysis_run.xml for the full analysis for each proc_pol combination
    """
    debug = False