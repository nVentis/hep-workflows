from typing import cast
import os.path as osp

from .utils.tasks import BaseTask
import luigi, law
import numpy as np

class AbstractCreateChunks(BaseTask):
    """Base class for CreateChunks tasks
    Require a luigi.IntParameter jobtime for the target job runtime
    in seconds.

    Args:
        BaseTask (_type_): _description_

    Raises:
        NotImplementedError: _description_

    Returns:
        _type_: _description_
    """
    fraction:float = cast(float, luigi.FloatParameter(description='Ratio of available events (as estimated from AbstractIndex task)', default=1.))
    
    overview:bool = cast(bool, luigi.BoolParameter(description='Whether or not to force showing the overview when the task is already done.', default=False))
    
    # time to start up Marlin; is substracted in the RuntimeAnalysis
    T0_MARLIN:int = 10
    
    def requires(self):
        raise NotImplementedError("""requires must be implemented by an inheriting class and return at least two items with a third optional:
first a task implementing AbstractIndex
second a task implementing AbstractMarlin
[third, optional: a task implementing AbstractCreateChunks; this will be assumed to be the basis for a MarlinTask giving rise to the samples in AbstractIndex]""")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def output(self):
        return [
            self.local_target('chunks.npy'),
            self.local_target('runtime_analysis.npy'),
            self.local_target('time_per_event.npy'),
            self.local_target('process_normalization.npy'),
            
            self.local_target('chunks.csv'),
            self.local_target('runtime_analysis.csv'),
            self.local_target('time_per_event.csv'),
            self.local_target('process_normalization.csv'),
        ]
    
    def custom_statistics(self)->None|list[tuple[float, list[str]]|tuple[float|list[str]|str]]:
        """If not None, can be used to adjust the number of used events per process using the custom_statistics argument of get_sample_chunk_splits.

        If a list of two-element tuples, the first element will be the ratio of events to use, and the second a list of processes (e.g. e2e2hh).
        If three-element tuples are supplied, the third element may either be 'total' or 'expected'.  

        Returns:
            None|list[tuple[float, list[str]]|tuple[float|list[str]|str]]: _description_
        """

        # e.g. config.custom_statistics
        
        return None
    
    def run(self):
        from .utils.runtime_analysis import get_runtime_analysis, get_adjusted_time_per_event
        from .utils.normalization import get_process_normalization, get_sample_chunk_splits, construct_sample_groups, CHUNK_SPLIT_MODES
        
        # inputs
        inputs = self.input()
        input_targets = {
            'index': inputs[0],
            'marlin': inputs[1]
        }
        
        PROCESS_INDEX = input_targets['index'][0].path
        SAMPLE_INDEX = input_targets['index'][1].path
        DATA_ROOT = osp.dirname(input_targets['marlin']['collection'][0][0].path)
        
        processes = np.load(PROCESS_INDEX)
        samples = np.load(SAMPLE_INDEX)
        
        # construct sample_groups
        sample_groups = None

        if len(inputs) > 2:
            src_chunks = np.load(inputs[2][0].path)
            sample_groups = construct_sample_groups(src_chunks, samples)
        
        runtime_analysis = get_runtime_analysis(DATA_ROOT)
        process_normalization = get_process_normalization(processes, samples,
                                                          RATIO_BY_TOTAL=self.fraction)
        time_per_event = get_adjusted_time_per_event(runtime_analysis, T0=self.T0_MARLIN)

        chunks = get_sample_chunk_splits(samples, process_normalization=process_normalization,
                    adjusted_time_per_event=time_per_event, MAXIMUM_TIME_PER_JOB=cast(int, self.jobtime),
                    custom_statistics=self.custom_statistics(), sample_groups=sample_groups,
                    split_mode=CHUNK_SPLIT_MODES['ONE_TO_MANY'] if sample_groups is None else CHUNK_SPLIT_MODES['MANY_TO_MANY'])
        
        BaseTask.touch_parent(self.output()[0])
        
        np.save(str(self.output()[0].path), chunks)
        np.save(str(self.output()[1].path), runtime_analysis)
        np.save(str(self.output()[2].path), time_per_event)
        np.save(str(self.output()[3].path), process_normalization)
        
        # For compatability, also save the final results as CSV
        np.savetxt(str(self.output()[4].path), chunks, delimiter=',', fmt='%s', header=','.join(chunks.dtype.names))
        np.savetxt(str(self.output()[5].path), runtime_analysis, delimiter=',', fmt='%s', header=','.join(runtime_analysis.dtype.names))
        np.savetxt(str(self.output()[6].path), time_per_event, delimiter=',', fmt='%s', header=','.join(time_per_event.dtype.names))
        np.savetxt(str(self.output()[7].path), process_normalization, delimiter=',', fmt='%s', header=','.join(process_normalization.dtype.names))
        
        self.printOverview()
        
    def printOverview(self):
        from law.util import colored
        from .utils.task_overviews import chunk_overview
        
        chunks = np.load(str(self.output()[0].path))
        time_per_event = np.load(str(self.output()[2].path))
        process_normalization = np.load(str(self.output()[3].path))
        
        self.publish_message(colored(chunk_overview(chunks, time_per_event, process_normalization, self),
                                     color='green', background='black'))
        
    def complete(self):
        complete = super().complete()
        
        if complete and self.overview:
            self.printOverview()
        
        return complete

class CreateRecoChunks(AbstractCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each job. Uses DESY NAF defaults for the vanilla queue.', default=7200))
    
    T0_MARLIN = 16
    
    def requires(self):
        from .tasks_index import RawIndex
        from .tasks_marlin import RecoRuntime
        return [ RawIndex.req(self), RecoRuntime.req(self) ]

class CreateAnalysisChunks(AbstractCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each job. Uses DESY NAF defaults for the vanilla queue.', default=1800))
    
    T0_MARLIN = 2
    
    def requires(self):
        from .tasks_index import AnalysisIndex
        from .tasks_marlin import AnalysisRuntime
        return [ AnalysisIndex.req(self), AnalysisRuntime.req(self), CreateRecoChunks.req(self) ]