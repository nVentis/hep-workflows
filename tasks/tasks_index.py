from abc import ABC, abstractmethod
from typing import cast

from .utils import BaseTask, ProcessIndex
import luigi, law
import numpy as np

class AbstractIndex(ABC, BaseTask):
    """This task creates two indeces:
    1. samples.npy: An index of available SLCIO sample files with information about the file location, number of events, physics process and polarization
    2. processes.npy: An index containing all encountered physics processes for each polarization and their cross section-section values 
    """
    index: ProcessIndex
    overview:bool = cast(bool, luigi.BoolParameter(description='Whether or not to force showing the overview when the task is already done.', default=False))
    
    @abstractmethod
    def slcio_files(self) -> list[str]:
        """This method must return a list of input LCIO files to index

        Returns:
            list[str]: _description_
        """
        pass
    
    def output(self):
        return [
            self.local_target('processes.npy'),
            self.local_target('samples.npy'),
            self.local_target('processes.csv'),
            self.local_target('samples.csv')
        ]
    
    def run(self):
        temp_files: list[law.LocalFileTarget] = self.output()
        BaseTask.touch_parent(temp_files[0])

        self.index = index = ProcessIndex(str(temp_files[0].path), str(temp_files[1].path), self.slcio_files())
        self.index.load()
        
        # For compatability, also save as CSV
        np.savetxt(cast(str, self.output()[2].path), index.processes, delimiter=',', fmt='%s', header=','.join(cast(np.ndarray, index.processes).dtype.names))
        np.savetxt(cast(str, self.output()[3].path), index.samples, delimiter=',', fmt='%s', header=','.join(cast(np.ndarray, index.samples).dtype.names))
        
        self.publish_message(f'Loaded {len(index.samples)} samples and {len(index.processes)} processes')
        self.printOverview()
    
    def complete(self):
        complete = super().complete()
        
        if complete and self.overview:
            self.printOverview()
            
        return complete
    
    def printOverview(self):
        from law.util import colored
        from .utils.task_overviews import index_overview
        
        processes = np.load(str(self.output()[0].path))
        samples = np.load(str(self.output()[1].path))
        
        self.publish_message(colored(index_overview(samples, processes, self), color='green', background='black'))


class RawIndex(AbstractIndex):
    def requires(self):
        from .framework import configurations
        return configurations.get(str(self.tag)).raw_index_requires(self)

class AnalysisIndex(AbstractIndex):
    def requires(self):
        from .framework import configurations
        return configurations.get(str(self.tag)).analysis_index_requires(self)
    
    def slcio_files(self):
        reco_final_target_collection = self.input()[0]['collection']
        
        # reco_final_target_collection[i][0] is directory, [i][1] is file
        reco_slcio_files = [reco_final_target_collection[i][1].path for i in range(len(reco_final_target_collection))]
        
        return reco_slcio_files