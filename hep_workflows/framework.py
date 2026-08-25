# coding: utf-8

from enum import Enum
from collections.abc import Callable
from typing import Optional, Union, TYPE_CHECKING, Any, Literal
import os

from .utils.types import SGVOptions, WhizardOption
from .utils.tasks import BaseTask
from law import Task
import luigi
import law, law.util, law.contrib, law.contrib.htcondor, law.job.base, law.contrib.htcondor.workflow

class EVENT_SIM_ENUM(Enum):
    FAST_SGV = 'fast_sgv'
    FULL_DDSIM = 'full_ddsim'

ValidSimValue = Literal['fast_sgv', 'full_ddsim']

if TYPE_CHECKING:
    from .tasks_sim import FastSimSGV
    from .tasks_index import RawIndex, AnalysisIndex

def all_subclasses(cls):
    subclasses = set(cls.__subclasses__())

    for sub in cls.__subclasses__():
        subclasses.update(all_subclasses(sub))

    return subclasses

class TaskRegistry:
    """Helper to resolve task classes from their name
    Can only find tasks inheriting from one of rootClasses
    """
    def __init__(self, rootClasses:list[Task]=[BaseTask]):
        self.rootClasses = rootClasses

    def resolveClasses(self):
        res = {}

        for cls in self.rootClasses:
            classes = all_subclasses(cls)
            res.update({c.__name__: c for c in classes})
            
        return res

    def addRootClass(self, cls:Task):
        self.rootClasses.append(cls)

    def findClass(self, cls_name:str):
        registry = self.resolveClasses()

        if cls_name in registry:
            return registry[cls_name]
        else:
            raise ValueError(f'Class {cls_name} not found in registry. Available classes: {", ".join(registry.keys())}')
        
task_registry = TaskRegistry()

# the htcondor workflow implementation is part of a law contrib package
# so we need to explicitly load it
law.contrib.load('htcondor')

class HTCondorWorkflow(law.contrib.htcondor.HTCondorWorkflow):
    max_runtime = law.DurationParameter(
        default=3.0, # 10.0
        unit="h",
        significant=False,
        description='maximum runtime; default unit is hours; default: 1',
    )

    transfer_logs = luigi.BoolParameter(
        default=True,
        significant=False,
        description="transfer job logs to the output directory; default: True",
    )
    
    def __init__(self, *args, **kwargs):
        super(HTCondorWorkflow, self).__init__(*args, **kwargs)
        self.cwd = self.htcondor_output_directory().path

    def htcondor_output_directory(self):
        # the directory where submission meta data should be stored
        return law.LocalDirectoryTarget(self.local_path())

    def htcondor_bootstrap_file(self):
        # each job can define a bootstrap file that is executed prior to the actual job
        # configure it to be shared across jobs and rendered as part of the job itself
        bootstrap_file = law.util.rel_path(__file__, 'bootstrap.sh')
        return law.JobInputFile(bootstrap_file, share=True, render_job=True)

    def htcondor_job_config(self, config:law.job.base.BaseJobFileFactory.Config, branch_keys:list, branch_values:list):
        # render_variables are rendered into all files sent with a job
        if 'REPO_ROOT' in os.environ:
            config.render_variables['REPO_ROOT'] = os.getenv('REPO_ROOT')
        
        config.render_variables['DOT_ENVIRONMENT_FILE'] = os.getenv('DOT_ENVIRONMENT_FILE', '')
        config.render_variables['SH_ENVIRONMENT_FILE'] = os.getenv('SH_ENVIRONMENT_FILE', '')
        config.render_variables['K4H_RELEASE'] = os.getenv('K4H_RELEASE', '')
        
        config.render_variables['ANALYSIS_PATH'] = os.getenv('ANALYSIS_PATH', '')
        config.render_variables['DATA_PATH'] = os.getenv('DATA_PATH')

        # copy the entire environment
        #config.custom_content.append(('getenv', 'true'))
        #config.custom_content.append(('request_cpus', '1'))
        
        name:Optional[str] = None
        for key, value in config.custom_content:
            if key == 'initialdir':
                name = os.path.basename(os.path.dirname(value))
        
        # Default at DESY NAF: 1.5GB RAM and 3h of runtime
        config.custom_content.append(('request_memory', '3000 Mb'))
        #if self.max_runtime:
        #    config.custom_content.append(('request_runtime', math.floor(cast(int|float, self.max_runtime) * 3600)))
        
        config.custom_content.append(('requirements', 'Machine =!= LastRemoteHost'))
        config.custom_content.append(('max_idle', 4000))

        return config

# default task dependencies injected into compatible tasks

class AnalysisConfiguration:
    """Base class for defining law task tags that contain steering information over multiple tasks and to inject task dependencies.

    Raises:
        Exception: _description_

    Returns:
        _type_: _description_
    """
    
    tag:str

    # COM energy
    sqrt_s:float

    # which simulation to use; only accepts items within EVENT_SIM_ENUM
    # defaults to SGV fast simulation
    simulation:ValidSimValue = 'fast_sgv'
    
    # possible entries: MarlinBaseJob
    # e.g. 'MarlinBaseJob': { 'analysis_runtime_n_files_to_process': 0, 'steering_file': 'some path.xml' }
    task_kwargs:dict[str, dict] = {}
    
    # whizard_options: should return a list of whizard option entries,
    # where one entry is for each process to generate
    whizard_options:Optional[list[WhizardOption]] = None
    
    task_dependencies:dict[str, list[Callable[['AnalysisConfiguration', 'Task'], dict[str, 'Task']]]] = {
        'FastSimSGV': [
            lambda config, this_task: { } if config.whizard_options is None and config.simulation != EVENT_SIM_ENUM.FAST_SGV else
                { 'whizard_event_generation': task_registry.findClass('WhizardEventGeneration').req(this_task) }
        ],
        'AnalysisIndex': [
            lambda config, this_task: { 'reco_final': task_registry.findClass('RecoFinal').req(this_task) }
        ],
        'RawIndex': [
            lambda config, this_task: { 'fast_sim': task_registry.findClass('FastSimSGV').req(this_task) } if config.sgv_inputs is not None else { },
            # for the full ddsim simulation path there is no fast-sim-like intermediate step: RawIndex
            # directly indexes WhizardEventGeneration's raw, generator-level LCIO output, which is what
            # DDSimFinal (see tasks_sim_full.py) then reads as ddsim input
            lambda config, this_task: { 'whizard_event_generation': task_registry.findClass('WhizardEventGeneration').req(this_task) }
                if config.simulation == EVENT_SIM_ENUM.FULL_DDSIM and config.whizard_options is not None else { }
        ]
    }

    def add_task_dependency(self, task_name:str, dependency_func:Callable[['AnalysisConfiguration', 'Task', 'Task'], dict[str, 'Task']]):
        if not task_name in self.task_dependencies:
            self.task_dependencies[task_name] = []

        self.task_dependencies[task_name].append(dependency_func)

    def task_requires(self, task:Task, requirements:dict[str, Task]):
        task_name = task.__class__.__name__

        if task_name in self.task_dependencies:
            for dependency_func in self.task_dependencies[task_name]:
                dependencies = dependency_func(self, task)

                for key, value in dependencies.items():
                    requirements[key] = value
        
        return requirements

    def sgv_requires(self, sgv_task: 'FastSimSGV', requirements:dict[str, Task]):
        if self.whizard_options is not None:
            # when using Whizard, we require fast sim
            if not isinstance(self.sgv_inputs, Callable):
                raise Exception('sgv_inputs must be defined when generating whizard events')
            
            from .tasks_generator import WhizardEventGeneration            
            requirements['whizard_event_generation'] = WhizardEventGeneration.req(sgv_task)
    
    # these optional properties can overwrite steering options, the executable
    # and base steering file to use for FastSimSGVExternalReadJob tasks 
    sgv_inputs:Optional[Callable[['FastSimSGV'], tuple[list[str], list[SGVOptions]]]] = None
    sgv_steering_file_src:str|None = None
    
    def analysis_index_requires(self, analysis_index_task: 'AnalysisIndex'):
        """Must return a dictionary with a key 'reco_final'
        pointing to task.req(analysis_index_task) of a task
        producing samples with high-level reconstruction (HLR)
        done. Defaults to RecoFinal for FastSimSGV, but may be
        overwritten for other tasks
        
        """
        from .tasks_marlin import RecoFinal
        return { 'reco_final': RecoFinal.req(analysis_index_task) }      
    
    """All SLCIO files that should be included in the analysis"""
    slcio_files:Optional[Union[list[str], Callable[['FastSimSGV'], list[str]]]] = None
    
    """Fration of available events that will be used for all channels
    Will only be used if not 1.
    DEPRECATED: Not used anymore. Instead, use the --fraction parameter to
        AbstractCreateChunks tasks
    """
    statistics:float = 1. 
    
    """If custom_statistics is a list of entries, it will be assumed as custom_statistics
    input for the get_chunk_splits function. Each entry should have the following
    shape:
        first: a number/ratio.
        second: the physics processes
        third, optional: reference; either 'expected' or 'total'. defaults to total.
        
    Example: [100, ["e1e1hh", "e2e2hh", "e3e3hh", "e1e1qqh", "e2e2qqh", "e3e3qqh",
    "n1n1hh", "n23n23hh", "n1n1qqh", "n23n23qqh",
    "qqhh", "qqqqh"], "expected"]
    """
    custom_statistics:Optional[list] = None
    
    marlin_globals:dict[str,Union[int,float,str]] = {}
    marlin_constants:dict[str,Union[int,float,str]]|Callable[[int, Any], dict[str,Union[int,float,str]]] = {}

    def __init__(self):
        """Defines parameters and functions to inject into law tasks
        at runtime.

        Returns:
            _type_: _description_
        """
        
        # if not slcio files are supplied, add the outputs from SGV
        # if any other case, slcio_files must be implemented manually
        if self.sgv_inputs is not None and self.slcio_files is None:
            def slcio_files(raw_index_task: 'RawIndex'):
                input_targets = raw_index_task.input()[0]['collection'].targets.values()

                return [f.path for f in input_targets]

            self.slcio_files = slcio_files

        # for the full ddsim simulation path (see tasks_sim_full.py), RawIndex indexes
        # WhizardEventGeneration's raw output directly (mirroring the role FastSimSGV's
        # output plays for the SGV path above), so default slcio_files accordingly
        if self.simulation == EVENT_SIM_ENUM.FULL_DDSIM and self.whizard_options is not None and self.slcio_files is None:
            def slcio_files(raw_index_task: 'RawIndex'):
                collection = raw_index_task.input()['whizard_event_generation']['collection']

                return [collection[i][0].path for i in range(len(collection))]

            self.slcio_files = slcio_files

    # Provide a key-value storage. This is used to define defaults
    storage:dict[str, Any] = {}

    def setProperty(self, property:str, value:Any):
        self.storage[property] = value

    def getPropery(self, property:str):
        return self.storage[property]
    
    def hasProperty(self, property:str):
        return property in self.storage

    def removeProperty(self, property:str):
        del self.storage[property]

class Registry():
    definitions:dict = {}
    
    def __init__(self, cls:Callable):
        self._cls = cls
    
    def add(self, config):
        if config.tag == '':
            raise ValueError(f'Tag must be defined for configuration')
        
        if config.tag in self.definitions:
            raise ValueError(f'Configuration with tag <{config.tag}> already exists')
        
        #if not isinstance(config, self._cls):
        #    raise ValueError(f'Configuration with tag <{config.tag}> is not of type <{self._cls.__name__}>')
        
        self.definitions[config.tag] = config
        
    def get(self, tag:str):
        if not tag in self.definitions:
            raise ValueError(f'Tag <{tag}> not a known configuration. Make sure to register it via configurations.add() before framework.py is executed')
        
        return self.definitions[tag]
    
class AnalysisConfigurationRegistry(Registry):
    def __init__(self):
        super().__init__(AnalysisConfiguration)
        
    def add(self, config:AnalysisConfiguration):
        super().add(config)
    
    def get(self, tag:str)->AnalysisConfiguration:
        return super().get(tag)    

# Create the registry and load the configurations
configurations = AnalysisConfigurationRegistry()

default = AnalysisConfiguration()