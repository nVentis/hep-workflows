from typing import cast, Union, TYPE_CHECKING
from collections.abc import Callable

from .utils import BaseTask, ProcessIndex
import luigi, law
import numpy as np

if TYPE_CHECKING:
    from .framework import AnalysisConfiguration

class AbstractIndex(BaseTask):
    """This task creates two indeces:
    1. samples.npy: An index of available LCIO/edm4hep.root sample files with information about the file location, number of events, physics process and polarization
    2. processes.npy: An index containing all encountered physics processes for each polarization and their cross section-section values

    input_files() must be implemented by the inheriting class. It may return LCIO (.slcio) or
    edm4hep (.edm4hep.root) files, but not both.
    """
    index: ProcessIndex
    overview:bool = cast(bool, luigi.BoolParameter(description='Whether or not to force showing the overview when the task is already done.', default=False))
    
    def input_files(self) -> list[str]:
        """This method must return a list of input files to index, either LCIO files or edm4hep files.
        LCIO files carry their physics information (process, polarization, cross-section...), edm4hep
        files do not: it is recovered from their meta.json sidecars (see AbstractRecoAna) and the index of
        an earlier stage, which must then be a requirement under the key 'upstream_index'.

        Returns:
            list[str]: _description_
        """
        raise NotImplementedError(f'{self.__class__.__name__} must implement input_files()')

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

        files = self.input_files()
        
        if not files:
            raise Exception(f'No input files to index in {self.__class__.__name__}')
        
        is_edm4hep = [f.endswith('.edm4hep.root') for f in files]
        if any(is_edm4hep) and not all(is_edm4hep):
            raise Exception('Indexing a mix of edm4hep and LCIO files is not supported')

        if all(is_edm4hep):
            from .utils.edm4hep import index_edm4hep_files

            upstream_index = self.input()['upstream_index']
            processes, upstream_samples = np.load(upstream_index[0].path), np.load(upstream_index[1].path)
            samples = index_edm4hep_files(files, processes, upstream_samples)

            np.save(str(temp_files[0].path), processes)
            np.save(str(temp_files[1].path), samples)
        else:
            self.index = index = ProcessIndex(str(temp_files[0].path), str(temp_files[1].path), files)
            self.index.load()

            processes, samples = index.processes, index.samples
        
        # For compatability, also save as CSV
        np.savetxt(cast(str, self.output()[2].path), processes, delimiter=',', fmt='%s', header=','.join(cast(np.ndarray, processes).dtype.names))
        np.savetxt(cast(str, self.output()[3].path), samples, delimiter=',', fmt='%s', header=','.join(cast(np.ndarray, samples).dtype.names))
        
        self.publish_message(f'Loaded {len(samples)} samples and {len(processes)} processes')
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


def resolve_files(task:BaseTask, config:'AnalysisConfiguration', prop:str)->list[str]:
    """Tries to fetch a file list from an AnalysisConfiguration given a
    property key. The resolved property should be a list or a function
    receiving the task and returning a list.
     
    Returns a sorted list of paths

    Args:
        task (BaseTask): _description_
        config (AnalysisConfiguration): _description_
        prop (str): _description_

    Raises:
        Exception: _description_

    Returns:
        list[str]: _description_
    """

    if not hasattr(config, prop):
        raise Exception(f'No property {prop} registered in config <{config.tag}>')

    source:Union[list[str], Callable[[BaseTask], list[str]], None] = getattr(config, prop)

    if callable(source):
        files = source(task)
    elif source is not None:
        files = source
    else:
        raise Exception(f'Could not parse result of {prop} in config <{config.tag}> to a list of files')        
        
    files = list(files)
    files.sort()
    return files

class GeneratorIndex(AbstractIndex):
    """Indexes the generator-level LCIO files AnalysisConfiguration.generator_files. These are
    the input to the simulation (FastSimSGV, or DDSimFinal, see tasks_sim_full.py).
    """
    def requires(self):
        from .framework import configurations
        return configurations.get(str(self.tag)).task_requires(self, { }) # call to inject dynamic workflow requirements

    def input_files(self) -> list[str]:
        from .framework import configurations
        
        return resolve_files(self, configurations.get(str(self.tag)), 'generator_files')

class RawIndex(AbstractIndex):
    """Indexes the input files for the high-level reconstruction, AnalysisConfiguration.high_level_reco_input_files.
    With a low-level reconstruction (low_level_reco), these are the edm4hep files produced by
    it (LowLevelRecoFinal, see tasks_low_level_reco.py)
    """
    def requires(self):
        from .framework import configurations
        #return configurations.get(str(self.tag)).raw_index_requires(self)
        return configurations.get(str(self.tag)).task_requires(self, { }) # call to inject dynamic workflow requirements

    def input_files(self) -> list[str]:
        from .framework import configurations
        
        return resolve_files(self, configurations.get(str(self.tag)), 'high_level_reco_input_files')


class AnalysisIndex(AbstractIndex):
    def requires(self):
        """Should return a dictionary with the result of a RecoFinal task at key 'reco_final' 

        Returns:
            _type_: _description_
        """
        from .framework import configurations
        #return configurations.get(str(self.tag)).analysis_index_requires(self)
        return configurations.get(str(self.tag)).task_requires(self, { }) # call to inject dynamic workflow requirements
    
    def input_files(self) -> list[str]:
        # reco_final_target_collection[i][0] is directory, [i][1] is file
        reco_final_target_collection = self.input()['reco_final']['collection']

        return [reco_final_target_collection[i][1].path for i in range(len(reco_final_target_collection))]
