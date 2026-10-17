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

class EVENT_ANALYSIS_ENUM(str, Enum):
    MARLIN = 'marlin'
    K4RUN = 'k4run'

ValidAnalysisValue = Literal['marlin', 'k4run']

if TYPE_CHECKING:
    from .tasks_sim import FastSimSGV
    from .tasks_index import AbstractIndex, RawIndex, AnalysisIndex

def event_generation_output_files(
        index_task:'AbstractIndex',
        event_generation:str='whizard_event_generation'
    )->list[str]:
    """Generator-level LCIO files produced by WhizardEventGeneration, which an index task
    has as a requirement under the key `event_generation` (see AnalysisConfiguration.task_dependencies)
    """
    collection = index_task.input()[event_generation]['collection']

    return [collection[i][0].path for i in range(len(collection))]

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
        description='reference job runtime; default unit is hours; default: 3. '
                    'On the first attempt this is NOT sent to the batch system (the '
                    'default reservation is used); it is the basis for the runtime '
                    'granted to automatically resubmitted jobs, see job_runtime_seconds().',
    )

    transfer_logs = luigi.BoolParameter(
        default=True,
        significant=False,
        description="transfer job logs to the output directory; default: True",
    )

    # --- runtime escalation for resubmitted jobs --------------------
    # A job the batch system killed for exceeding its reserved runtime is
    # resubmitted by law (status "retry"). On resubmission attempt N it is granted
    #     max_runtime * runtime_growth_per_retry ** N
    # seconds, capped at max_runtime * max_runtime_growth, so the few genuine
    # stragglers stop bouncing without changing the request for the bulk of jobs
    # (which keep running on the default, opportunistic reservation).
    # Scheduler-agnostic: job_runtime_seconds() returns plain seconds and only the
    # per-scheduler *_job_config() hook knows how to phrase it.
    runtime_growth_per_retry:float = 2.0
    max_runtime_growth:float = 4.0

    def job_runtime_seconds(self, job_nums) -> Optional[int]:
        """Wall time to request for the job(s) about to be (re)submitted, in
        seconds, or None to leave the batch-system default untouched.

        Args:
            job_nums: iterable of law job numbers in this submission (grouped
                submission) or a single job number (non-grouped). The escalation
                keys off the largest resubmission-attempt count among them; law
                persists job_data.attempts to <workflow_type>_jobs_*.json and
                reloads it, so the granted runtime also grows across separate
                `law run` invocations.

        Escalation based on the resubmission-attempt count only kicks in when
        the ``runtime_escalation`` parameter (see BaseWorkflowTask) is set;
        it defaults to False, so retries keep requesting the batch-system
        default runtime unless explicitly opted into.

        The result is additionally scaled by the ``runtime_multiplier`` parameter
        (see BaseWorkflowTask) when that is present and != 1, which also forces an
        explicit request on the very first attempt - handy to re-run a tag whose
        jobs timed out with more head room. This applies regardless of
        ``runtime_escalation``.
        """
        if not isinstance(job_nums, (list, tuple, set, frozenset)):
            job_nums = [job_nums]

        attempts = 0
        if getattr(self, 'runtime_escalation', False):
            try:
                job_data = self.workflow_proxy.job_data
                attempts = max((int(job_data.attempts.get(jn, 0)) for jn in job_nums), default=0)
            except Exception:
                pass

        multiplier = float(getattr(self, 'runtime_multiplier', 1.0) or 1.0)

        # first attempt and no manual override: keep the batch system default
        if attempts == 0 and abs(multiplier - 1.0) < 1e-9:
            return None

        base = float(self.max_runtime) * 3600.0
        growth = min(self.runtime_growth_per_retry ** attempts, self.max_runtime_growth)

        return max(60, int(round(base * growth * multiplier)))

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

        # only request an explicit runtime once a job has been resubmitted at least
        # once (job_runtime_seconds returns None on the first attempt); the bulk of
        # jobs thus keep the default reservation, while stragglers are retried with
        # progressively more head room
        runtime_seconds = self.job_runtime_seconds(branch_keys)
        if runtime_seconds is not None:
            runtime_seconds = int(runtime_seconds)
            self.publish_message(f'Submitting jobs with non-default runtime of {runtime_seconds} seconds')
            config.custom_content.append(('+RequestRuntime', runtime_seconds))

        config.custom_content.append(('requirements', 'Machine =!= LastRemoteHost'))
        config.custom_content.append(('max_idle', 4000))

        return config


# BaseWorkflowTask lives in its own module (utils/tasks/BaseWorkflowTask.py) but is
# imported here after HTCondorWorkflow is defined so existing
# `from .framework import BaseWorkflowTask` imports keep working
from .utils.tasks.BaseWorkflowTask import BaseWorkflowTask


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

    # which framework to use for the high-level reconstruction AND the analysis;
    # only accepts items within EVENT_ANALYSIS_ENUM
    # - 'marlin' (default): Marlin based RecoRuntime/RecoFinal and AnalysisRuntime/AnalysisFinal
    # - 'k4run': Gaudi/k4run based K4RunHighLevelReco* and K4RunAnalysis* tasks. for now, requires simulation = 'full_ddsim'
    analysis:ValidAnalysisValue = 'marlin'
    
    # possible entries: MarlinBaseJob
    # e.g. 'MarlinBaseJob': { 'analysis_runtime_n_files_to_process': 0, 'steering_file': 'some path.xml' }
    task_kwargs:dict[str, dict] = {}
    
    # whizard_options: should return a list of whizard option entries,
    # where one entry is for each process to generate
    whizard_options:Optional[list[WhizardOption]] = None
    
    task_dependencies:dict[str, list[Callable[['AnalysisConfiguration', 'Task'], dict[str, 'Task']]]] = {
        'FastSimSGV': [
            lambda config, this_task: { } if config.whizard_options is None and config.simulation != EVENT_SIM_ENUM.FAST_SGV else
                { 'whizard_event_generation': task_registry.findClass('WhizardEventGeneration').req(this_task) },
            # index of the generator-level input of the fast simulation, if it is known (see generator_files)
            lambda config, this_task: { 'generator_index': task_registry.findClass('GeneratorIndex').req(this_task) }
                if config.generator_files is not None else { }
        ],
        'AnalysisIndex': [
            lambda config, this_task: { 'reco_final': task_registry.findClass('RecoFinal').req(this_task) } if not config.uses_k4run_analysis else
                # for k4run based analysis, AnalysisIndex indexes the edm4hep output of the high-level
                # reconstruction; the process information is taken from the GeneratorIndex
                { 'reco_final': task_registry.findClass('K4RunHighLevelRecoFinal').req(this_task),
                  'generator_index': task_registry.findClass('GeneratorIndex').req(this_task) }
        ],
        'GeneratorIndex': [
            # GeneratorIndex indexes the generator-level LCIO files, i.e. WhizardEventGeneration's raw
            # output if whizard_options are given. These are the input to the simulation, i.e. to FastSimSGV
            # and DDSimFinal (see tasks_sim_full.py)
            lambda config, this_task: { 'whizard_event_generation': task_registry.findClass('WhizardEventGeneration').req(this_task) }
                if config.whizard_options is not None else { }
        ],
        'RawIndex': [
            lambda config, this_task: { 'fast_sim': task_registry.findClass('FastSimSGV').req(this_task) } if config.sgv_inputs is not None else { },
            # with k4run based analysis, RawIndex describes the output of the low-level reconstruction
            # which serves as the input to the high-level reconstruction
            lambda config, this_task: {
                'k4run_low_level_reco_final': task_registry.findClass('K4RunLowLevelRecoFinal').req(this_task),
                'generator_index': task_registry.findClass('GeneratorIndex').req(this_task)
            } if config.uses_k4run_analysis else { }
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
    
    """For fast-sim workflows: All SLCIO files that should be included in the analysis
    (i.e. after low-level-reconstruction and ParticleFlow, before high-level-reco). 
    For full-sim workflows: See high_level_reco_input_files() instead."""
    slcio_files:Optional[Union[list[str], Callable[['FastSimSGV'], list[str]]]] = None

    @property
    def generator_files(self)->Optional[Union[list[str], Callable[['AbstractIndex'], list[str]]]]:
        """All generator-level LCIO files that are input to simulation (SGV or ddsim),
        indexed by GeneratorIndex. Either a list of paths or a function receiving the
        GeneratorIndex task and returning such a list. May be overwritten by inheriting
        classes.

        Defaults to
        - the output of WhizardEventGeneration, if whizard_options are given (GeneratorIndex then
            requires WhizardEventGeneration, see task_dependencies)
        - else None; GeneratorIndex is then not required by FastSimSGV, and must be
            provided for full-sim workflows
        """
        if self.whizard_options is not None:
            return event_generation_output_files

        return None

    @property
    def uses_k4run_analysis(self)->bool:
        return self.analysis == EVENT_ANALYSIS_ENUM.K4RUN

    @property
    def high_level_reco_input_files(self)->Optional[Union[list[str], Callable[['RawIndex'], list[str]]]]:
        """All files that are the input to the high-level reconstruction, i.e. the files
        indexed by RawIndex. Either a list of paths or a function receiving the RawIndex
        task and returning such a list. May be overwritten by inheriting classes.

        Defaults to
        - for analysis = 'k4run': the edm4hep output of K4RunLowLevelRecoFinal; RawIndex then
            requires K4RunLowLevelRecoFinal (see task_dependencies)
        - else (legacy): slcio_files
        """

        if self.uses_k4run_analysis:
            
            def k4run_low_level_reco_output_files(raw_index_task: 'RawIndex')->list[str]:
                # edm4hep files produced by K4RunLowLevelRecoFinal which RawIndex requires
                
                targets = raw_index_task.input()['k4run_low_level_reco_final']['collection'].targets

                return [str(targets[branch].path) for branch in sorted(targets)]

            return k4run_low_level_reco_output_files

        return self.slcio_files
    
    statistics:float = 1. 
    """Fration of available events that will be used for all channels
    Will only be used if not 1.
    DEPRECATED: Not used anymore. Instead, use the --fraction parameter to
        AbstractCreateChunks tasks
    """
    
    custom_statistics:Optional[list] = None
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
    
    marlin_globals:dict[str,Union[int,float,str]] = {}
    marlin_constants:dict[str,Union[int,float,str]]|Callable[[int, Any], dict[str,Union[int,float,str]]] = {}

    def __init__(self):
        """Defines parameters and functions to inject into law tasks
        at runtime.

        Returns:
            _type_: _description_
        """
        
        if self.analysis not in [item.value for item in EVENT_ANALYSIS_ENUM]:
            raise ValueError(f'Invalid analysis <{self.analysis}> in configuration <{self.tag}>. Must be one of {[item.value for item in EVENT_ANALYSIS_ENUM]}')

        if self.uses_k4run_analysis and self.simulation != EVENT_SIM_ENUM.FULL_DDSIM:
            raise ValueError(f"analysis = 'k4run' requires simulation = EVENT_SIM_ENUM.FULL_DDSIM in configuration <{self.tag}>")

        # if no slcio files are supplied, add the outputs from SGV
        # if any other case, slcio_files must be implemented manually
        if self.sgv_inputs is not None and self.slcio_files is None:
            def slcio_files(raw_index_task: 'RawIndex'):
                input_targets = raw_index_task.input()['fast_sim']['collection'].targets.values()

                return [f.path for f in input_targets]

            self.slcio_files = slcio_files

    def setup():
        """method to setup a configuration before first use, e.g. to provision necessary files;
        setup() method will be called when an AnalysisConfiguration is first read by an
        AnalysisConfigurationRegistry
        """
        
        pass

    is_setup = False

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
    
    def add(self, item):
        if item.tag == '':
            raise ValueError(f'Tag must be defined for item')
        
        if item.tag in self.definitions:
            raise ValueError(f'Item with tag <{item.tag}> already exists')
        
        self.definitions[item.tag] = item
        
    def get(self, tag:str):
        if not tag in self.definitions:
            raise ValueError(f'Tag <{tag}> not a known item. Make sure to register it via registry.add() beforehand')
        
        return self.definitions[tag]
    
class AnalysisConfigurationRegistry(Registry):
    def __init__(self):
        super().__init__(AnalysisConfiguration)
        
    def add(self, config:AnalysisConfiguration):
        super().add(config)
    
    def get(self, tag:str)->AnalysisConfiguration:
        configuration:AnalysisConfiguration = super().get(tag)

        if not configuration.is_setup:
            configuration.setup()
            configuration.is_setup = True

        return configuration    

# Create the registry and load the configurations
configurations = AnalysisConfigurationRegistry()

default = AnalysisConfiguration()