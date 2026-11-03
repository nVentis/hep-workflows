from typing import cast
from collections.abc import Callable
from abc import ABC, abstractmethod
from types import MethodType
import os.path as osp

from .framework import BaseWorkflowTask, configurations
from .utils import ShellTask
from .utils.filenames import splitext_mod
from .utils.types import RecoAnaBranchValue, RecoAnaSteeringDict
from law.util import flatten
import numpy as np
import law

class AbstractRecoAna(ABC, ShellTask, BaseWorkflowTask, law.LocalWorkflow):
    """Abstract class for the reconstruction and analysis jobs after
    the simulation. Depending on the option of AnalysisConfiguration
    for the stage of the task (low_level_reco, high_level_reco or
    analysis, see stage), they run Marlin or k4run (a Gaudi steering
    file; see resources/k4run for examples), without any difference
    in what the task does.
    
    The parameters for running Marlin/k4run can be set here
    or overwritten in a child class by a custom imple-
    mentation of get_steering_parameters/build_run_command.
    
    Considers two targets per task branch:
    - output[0]: a directory, identified as the temp.
        working directory in which Marlin/k4run is run. Besides
        everything the steering file writes, it contains a sidecar
        meta.json (timing, number of events, process, ...)
    - output[1]: a file, the output_file (see RecoAnaBranchValue)
    
    Constants and globals are passed to Marlin as --constant.K=V
    and --global.K=V, and to k4run as --K V (both).
    """
    
    # the stage of the AnalysisConfiguration (low_level_reco, high_level_reco or analysis) selecting Marlin or k4run
    stage:str = 'high_level_reco'
    
    @property
    def uses_k4run(self)->bool:
        return self.config.uses_k4run(self.stage)
    
    @property
    def executable(self)->str:
        return 'k4run' if self.uses_k4run else 'Marlin'

    steering_file:str = 'steer.xml' # change this to your favorite steering file and make sure it's accessible (e.g. findable from an environment variable)
    
    # k4run only: path to the compact file describing the detector geometry, expandvars()-ready
    compact_file:str = ''

    # name of the file written by the steering file, to be moved to the file output location (output[1]).
    # It is stored in the branch values (see create_branch_map) and has to be read from there (see get_output_file),
    # as output() depends on it
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
    
    def get_steering_parameters(self)->RecoAnaSteeringDict:
        """The branch map self.branch_map is a dictionary
        branch => value where value has one of the following form:
        
        a) tuples: (input_files:list[str], n_events_skip:int, n_events_max:int)
        b) string: input_file

        Returns:
            dict: _description_
        """
        
        branch_value = cast(RecoAnaBranchValue, self.branch_map[self.branch])
        assert isinstance(branch_value, tuple)
        
        input_files, n_chunk_of_sample, n_chunks_in_sample, n_events_skip, n_events_max, mcp_col_name, output_bname, output_file = branch_value
        
        n_events_skip = n_events_skip if (n_events_skip is None or n_events_skip > -1) else self.n_events_skip
        n_events_max  = n_events_max  if n_events_max  > -1 else self.n_events_max
        
        if isinstance(input_files, str):
            input_files = [input_files]
        
        steering = RecoAnaSteeringDict(
            executable=self.executable,
            input_files= input_files,
            n_events_skip=n_events_skip,
            n_events_max=n_events_max,
            mcp_col_name=mcp_col_name,
            output_bname=output_bname,
            output_file=output_file
        )
        
        return steering
    
    def get_output_file(self)->str:
        return cast(RecoAnaBranchValue, self.branch_data)[-1]
    
    def get_temp_dir(self):
        return f'{self.htcondor_output_directory().path}/TMP-{self.output_name()}'
    
    def output_name(self):
        branch_data = cast(RecoAnaBranchValue, self.branch_data)
        input_file = branch_data[0]
        output_bname = branch_data[-2]
        
        if isinstance(input_file, str):
            sample_filename = osp.basename(input_file)
            n_chunk = branch_data[1]
            n_chunks_in_sample = branch_data[2]
            
            return f'{splitext_mod(sample_filename)[0]}.{n_chunk}-{n_chunks_in_sample}-{str(self.branch)}'
        elif isinstance(input_file, list) and isinstance(output_bname, str):
            return f'{output_bname}-{str(self.branch)}'
        else:
            raise Exception('Either input_file must be a string, or a list while output_bname is a str')
    
    def parse_globals(self) -> str:
        if not self.uses_k4run:
            keys = filter(lambda key: key not in ['MaxRecordNumber', 'LCIOInputFiles', 'SkipNEvents'], self.globals.keys())
            return ' '.join([f'--global.{key}="{self.globals[key]}"' for key in keys])
        
        return ' '.join([f'--{key} "{value}"' for key, value in self.globals.items()])
    
    def parse_constants(self) -> str:
        if not self.uses_k4run:
            return ' '.join([f'--constant.{key}="{value}"' for key, value in self.constants.items()])
        
        return ' '.join([f'--{key} "{value}"' for key, value in self.constants.items()])
    
    def build_run_command(self, steering:RecoAnaSteeringDict) -> str:
        """The part of the command running Marlin or k4run, to be run within the temporary working directory"""
        
        input_files = steering['input_files']
        n_events_skip = steering['n_events_skip']
        n_events_max = steering['n_events_max']
        executable = steering['executable']
        output_file = steering['output_file']
        
        if self.uses_k4run:
            assert self.compact_file, "compact_file must be set, e.g. via task_kwargs on an AnalysisConfiguration"
            files_arg = ' '.join(f'"{f}"' for f in input_files)

            cmd  = f'{executable} "{self.steering_file}" --inputFiles {files_arg}'
            cmd += f' --compactFile "{self.compact_file}" --outputFile "{output_file}"'
            # as for Marlin, 0 means all events
            cmd += f' -n {n_events_max if (n_events_max is not None and n_events_max > 0) else -1}'

            if n_events_skip is not None and n_events_skip > 0:
                # the reader depends on the format of the input
                cmd += f' --LcioEvent.skipNEvents={n_events_skip}' if input_files[0].endswith('.slcio') else f' --IOSvc.FirstEventEntry={n_events_skip}'
            
            return f'{cmd} {self.parse_constants()} {self.parse_globals()}'
        
        str_max_record_number = f' --global.MaxRecordNumber={str(n_events_max + 1 if (n_events_max > 0 and n_events_skip is not None and n_events_skip > 0) else n_events_max)}' if n_events_max is not None else ''
        str_skip_n_events = f' --global.SkipNEvents={str(n_events_skip)}' if (n_events_skip is not None and n_events_skip > 0) else ''
        
        # failures are caught by the checks below
        return f'( {executable} "{self.steering_file}" {self.parse_constants()} {self.parse_globals()}{str_max_record_number}{str_skip_n_events} --global.LCIOInputFiles="{" ".join(input_files)}" || true )'
    
    def count_events_command(self, steering:RecoAnaSteeringDict) -> str:
        """Shell command printing the number of events that were processed"""
        output_file = steering['output_file']
        
        if output_file.endswith('.slcio'):
            return f'lcio_event_counter "{output_file}"'
        elif output_file.endswith('.edm4hep.root'):
            return f'edm4hep_event_counter "{output_file}"'
        
        # no event-wise output (e.g. histograms): use the number of events in the input
        input_files, n_events_skip, n_events_max = steering['input_files'], steering['n_events_skip'], steering['n_events_max']
        counter = 'lcio_event_counter' if input_files[0].endswith('.slcio') else 'edm4hep_event_counter'
        
        cmd  = f'N=0; for f in {" ".join(input_files)}; do N=$((N+$({counter} "$f"))); done'
        cmd += f'; N=$((N-{n_events_skip if n_events_skip is not None and n_events_skip > 0 else 0}))'
        if n_events_max is not None and n_events_max > 0:
            cmd += f'; [ "$N" -gt {n_events_max} ] && N={n_events_max}'
        
        return cmd + '; echo "$N"'
    
    def sample_info(self, location:str) -> tuple[str, str]:
        """process and proc_pol of the sample at location, from the index"""
        samples = np.load(self.input()['index_task'][1].path)
        sample = samples[samples['location'] == location]
        assert len(sample) > 0, f'Sample {location} not found in the index'

        return str(sample['process'][0]), str(sample['proc_pol'][0])
    
    def build_command(self, **kwargs):
        steering = self.get_steering_parameters()
        
        input_files = steering['input_files']
        executable = steering['executable']
        output_file = steering['output_file']
        process, proc_pol = self.sample_info(input_files[0])
        
        temp = self.get_temp_dir()
        
        cmd =  f' echo "Starting {executable} at $(date)" && T_START=$(date +%s)'
        cmd += f' && rm -rf {self.htcondor_output_directory().path}/*-{str(self.branch)}'
        cmd += f' && mkdir -p "{temp}" && cd "{temp}"'
        cmd += f' && {self.build_run_command(steering)}'
        cmd += f' && echo "Finished {executable} at $(date)" && T_END=$(date +%s)'
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
        
        if output_file.endswith('.edm4hep.root'):
            cmd += f' && echo "Info: Checking with edm4hep_event_counter that file <{output_file}> contains events" && [ "$(edm4hep_event_counter {output_file})" -gt 0 ]'
        
        # sidecar with timing and physics information, read by the index and CreateChunks tasks
        # (also for outputs that are not event-wise, as the runtime analysis requires it)
        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s", "branch": %s}'
        cmd += f' && N_EVT=$( {self.count_events_command(steering)} )'
        cmd += f" && printf '{meta_fmt}' \"$T_START\" \"$T_END\" \"$N_EVT\" \"{process}\" \"{proc_pol}\" \"{','.join(input_files)}\" \"{self.branch}\" > meta.json"
        
        cmd += f' && mv "{output_file}" "{self.output()[1].path}" && cd .. && mv "{temp}" "{self.output()[0].path}" )'

        return cmd
    
    def output(self):
        return [
            self.local_directory_target(str(self.branch)),
            self.local_target(f'{self.branch}{splitext_mod(self.get_output_file())[1]}')
        ]
        
    def run(self, **kwargs):
        ShellTask.run(self, keep_cwd=True, **kwargs)


class RecoAnaBaseJob(AbstractRecoAna):
    """Base class for reconstruction and analysis jobs. Tasks subclassing this must imple-
    ment/define correctly:
    - output_file (see documentation of AbstractRecoAna)
    - workflow_requires() and requires(), which are expected to return:
        - 'index_task': task subclassing AbstractIndex
        - 'chunks': task subclassing AbstractCreateChunks, only
            required if self.debug is False (as is for
            [Analysis/Reco]Final tasks)

    Args:
        AbstractRecoAna (_type_): _description_

    Returns:
        _type_: _description_
    """
    debug = True
    
    # controls how many files are processed in debug mode (e.g. AnalysisRuntime). if None, all files are processed
    debug_n_files_to_process:int|None = 3
    
    # whether the name of the MCParticle collection of the input (from the index) is passed as
    # constant MCParticleCollectionName
    pass_mcp_col_name:bool = True
    
    def inject_task_kwargs(self):
        """Parameter injection from registered configurations: the entries of AnalysisConfiguration.task_kwargs
        for all classes in the inheritance chain, e.g. 'RecoAnaBaseJob' for all and 'RecoAbstract' only for RecoRuntime/RecoFinal
        (dictionaries or functions receiving the task and returning a dictionary). Functions given as values replacing a
        method of the task (e.g. build_run_command) are bound to the task and receive it as first argument, i.e.
        they may call e.g. AbstractRecoAna.build_run_command(self, steering)."""
        config = configurations.get(str(self.tag))
        
        for cls in reversed(type(self).__mro__):
            if cls.__name__ in config.task_kwargs:
                task_kwargs = config.task_kwargs[cls.__name__]
                
                for prop, value in (task_kwargs(self) if isinstance(task_kwargs, Callable) else task_kwargs).items():
                    if callable(value) and callable(getattr(type(self), prop, None)):
                        value = MethodType(value, self)

                    setattr(self, prop, value)
    
    # Attach constants/globals (and the MCParticleCollectionName)
    def pre_run_command(self, **kwargs):
        config = configurations.get(str(self.tag))
        
        self.inject_task_kwargs()
        
        # work on copies; the class attributes are shared by all tasks
        self.constants = dict(self.constants)
        self.globals = dict(self.globals)
        
        # the name of the MCParticle collection in the input; for k4run, steering files have to accept it
        if self.pass_mcp_col_name:
            self.constants['MCParticleCollectionName'] = self.get_steering_parameters()['mcp_col_name']
        
        constants = config.constants(self.branch, self.branch_data) if isinstance(config.constants, Callable) else config.constants
        for key, value in constants.items():
            self.constants[key] = str(value)
        
        for key, value in config.globals.items():
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
    def create_branch_map(self) -> dict[int, RecoAnaBranchValue]:
        branch_map:dict[int, RecoAnaBranchValue] = {}
        
        self.inject_task_kwargs()
        
        samples = np.load(self.input()['index_task'][1].path)
        
        if not self.debug:
            
            # The calculated chunking is used
            chunks = np.load(self.input()['chunks'][0].path)
            
            if 'sub_branch_size' in chunks.dtype.names:
                filecount = {}

                # group the chunk rows by branch in one pass
                # the sort is stable, so rows keep their array order within each branch
                order = np.argsort(chunks['branch'], kind='stable')
                branches, starts = np.unique(chunks['branch'][order], return_index=True)
                stops = np.append(starts[1:], len(order))

                locations = chunks['location'][order].tolist()
                src_bnames = chunks['src_bname'][order].tolist()

                # location -> mcp_col_name; if a location occurs more than once, the first one wins
                mcp_col_names = dict(zip(samples['location'].tolist()[::-1], samples['mcp_col_name'].tolist()[::-1]))

                for branch, start, stop in zip(branches.tolist(), starts.tolist(), stops.tolist()):
                    src_bname = src_bnames[start]
                    files = locations[start:stop]

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
                        mcp_col_names[files[0]], # require mcp_col_name to be equal
                        f'{src_bname}.{filecount[src_bname]}',
                        self.output_file
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
                        None,
                        self.output_file
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
                        None,
                        self.output_file
                    )
                    i += 1
        
        return branch_map

    @workflow_condition.output
    def output(self):
        output_name = self.output_name()
        output_file = self.get_output_file()
        assert('.' in output_file)
        
        return [
            self.local_directory_target(output_name),
            self.local_target(f'{output_name}{splitext_mod(output_file)[1]}')
        ]

class RecoAbstract(RecoAnaBaseJob):
    steering_file:str = '$MARLIN_RECO_STEERING_FILE' # 'REPO_ROOT/scripts/prod_reco_run.xml'
    output_file:str = 'reco.slcio'
    
    check_output_root_ttrees = None
    check_output_lcio_files = ['reco.slcio']
    
    def workflow_requires(self):
        from .tasks_index import RawIndex
        from .tasks_chunks import CreateRecoChunks
        
        reqs = {}
        reqs['index_task'] = RawIndex.req(self)
        
        if not self.debug:
            reqs['chunks'] = CreateRecoChunks.req(self)
        
        # inject dynamic workflow requirements from the registered configuration
        configurations.get(str(self.tag)).task_requires(self, reqs)
        
        return reqs

    def requires(self):
        # branch-level mirror of workflow_requires() so the dynamic
        # workflow_condition evaluates identically whether it is called on the
        # workflow or on a branch task (self.input() otherwise resolves to an
        # empty dict on branches -> all([]) == True -> condition wrongly "met")
        return self.workflow_requires()

class AnalysisAbstract(RecoAnaBaseJob):
    stage = 'analysis'
    
    steering_file:str = '$MARLIN_ANALYSIS_STEERING_FILE' # 'REPO_ROOT/scripts/prod_analysis_run.xml'
    output_file:str = 'AIDA.root'
    
    check_output_root_ttrees = [
        ('AIDA.root', 'FinalStates'),
    ]
    
    def workflow_requires(self):
        from .tasks_index import AnalysisIndex
        from .tasks_chunks import CreateAnalysisChunks
        
        reqs = {}
        reqs['index_task'] = AnalysisIndex.req(self)
        
        if not self.debug:
            reqs['chunks'] = CreateAnalysisChunks.req(self)
        
        return reqs

    def requires(self):
        # branch-level mirror of workflow_requires(); see RecoAbstract.requires()
        return self.workflow_requires()

class RecoRuntime(RecoAbstract):
    """Runs a runtime analysis of the high-level-reconstruction for each proc_pol combination
    """
    debug = True

class RecoFinal(RecoAbstract):
    """Runs the full high-level-reconstruction for each proc_pol combination
    """
    debug = False

class AnalysisRuntime(AnalysisAbstract):
    """Runs a runtime analysis of the channel-specific analysis for each proc_pol combination
    """
    debug = True

class AnalysisFinal(AnalysisAbstract):
    """Runs the full channel-specific analysis for each proc_pol combination
    """
    debug = False