import os.path as osp
import law
from abc import ABC, abstractmethod
from typing import Callable, cast
from .tasks_abstract import AbstractSGVExternalReadJob
from .utils.types import SGVOptions
from law.util import flatten

class FastSimSGV(AbstractSGVExternalReadJob):
    branch_data: tuple[str, SGVOptions]

    @abstractmethod
    def sgv_inputs(self)->tuple[list[str], list[SGVOptions]]:
        """_summary_

        Returns:
            tuple[list[str], list[SGVOptions]]: _description_
        """

        # config = configurations.get(str(self.tag))
        # assert(isinstance(config.sgv_inputs, Callable))
        # input_files, input_options = config.sgv_inputs(self)
        pass
    
    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))
        
    @workflow_condition.create_branch_map
    def create_branch_map(self):
        input_files, input_options = self.sgv_inputs()
        assert(len(input_files) == len(input_options))
        
        return { k: [file, options] for (k, file, options) in zip(
            list(range(len(input_files))),
            input_files,
            input_options
        )}
    
    @workflow_condition.output
    def output(self):
        # output filename = input filename but extension changed to 'slcio'; necessary for stdhep input
        return self.local_target(f'{osp.splitext(osp.basename(self.branch_data[0]))[0]}.slcio')