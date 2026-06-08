import os.path as osp
import law
from abc import abstractmethod
from typing import cast

from .utils.types import SGVOptions
from law.util import flatten
from .framework import configurations, HTCondorWorkflow
from .utils import ShellTask, SGVSteeringModifier
import law, uuid

class AbstractSGVExternalReadJob(ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    """Abstract class for fast simulation jobs using SGV, reading in
    LCIO/STDHEP and out-putting LCIO files
    
    We assume a working installation of SGV using the -EXTREAD option
    with LCIO/STDHEP support. This can be achieved by following the
    steps in https://gitlab.desy.de/mikael.berggren/sgv specifically
    in the samples directory.
    
    We assume sourcing sgv_env and calling the executable usesgvlcio
    works provided the input_file exists. This can be accomplished by
    using the default options when installing sgv.
    We thus copy the directory including the executable to the working
    node, symlink the input file to a location given by input_file and
    expect the output at output_file (again within the current working
    directory).
    The executable defaults to '$SGV_DIR/tests/usesgvlcio.exe', but
    can be overwritten with AnalysisConfiguration.sgv_executable, if
    this is a string.
    
    Assign the location to SGV_DIR in the .env file
    
    The parameters for running SGV can be set here or overwritten in a
    child class by a custom implementation of get_steering_file. Per
    default, custom SGV steering options can be supplied using
    AnalysisConfiguration.sgv_inputs.

    A base steering file must be supplied via steering_file_src. Any
    custom steering options are merged into the job's steering file on
    the fly (see SGVSteeringModifier). The location of the base file
    is defined in steering_file_src and can be customized using
    AnalysisConfiguration.sgv_steering_file_src.
    """
    
    @property
    def executable(self)->str:
        return '$SGV_DIR/tests/usesgvlcio.exe'
    
    # this can be changed, if desired
    @property
    def steering_file_src(self)->str:
        return '$SGV_DIR/tests/sgv.steer'
    
    # this must fit the compilation of usesgvlcio and should not needed to be changed
    steering_file_fortran_unit = 'fort.17'
    
    sgv_env = '$SGV_DIR/sgvenv.sh'
    sgv_input = 'input.slcio' # this must fit the steering file, also the GENERATOR_INPUT_TYPE
    sgv_output = 'sgvout.slcio' # this must fit the steering file
    
    # False to allow for checks
    tmp_steering_name = 'sgv-final.steer'
    tmp_dir: str|None = None
    
    def get_steering_file(self)->str:
        """Default implementation for creating a SGV steering
        file. Reads in steering_file_src, merges any options in
        input_options and returns the content for the steering
        file.

        Args:
            branch (int): _description_
            input_file (str): _description_

        Returns:
            str: merged steering file content
        """
        
        input_file, input_options = cast(tuple[str, SGVOptions], self.branch_data)
        
        # change the name of the expected input file to SGV if it was supplied
        # in input_options
        if isinstance(input_options, dict) and 'external_read_generation_steering.INPUT_FILENAMES' in input_options:
            self.sgv_input = input_options['external_read_generation_steering.INPUT_FILENAMES']
        
        modifier = SGVSteeringModifier(osp.expandvars(self.steering_file_src))
        
        return modifier.merge_properties(input_options if isinstance(input_options, dict) else {})
    
    def get_temp_dir(self):
        if not self.tmp_dir:
            output_path = cast(str, self.output().path)
            self.tmp_dir = f'{osp.dirname(output_path)}/TMP-{osp.splitext(osp.basename(output_path))[0]}-{str(uuid.uuid4())}'
            
        return self.tmp_dir
    
    def build_command(self, **kwargs):    
        input_file, input_options = cast(tuple[str, SGVOptions], self.branch_data)
        target_path = str(self.output().path)
        
        steering_file_content = self.get_steering_file()
        with open(f'{kwargs["cwd"]}/{self.tmp_steering_name}', 'w') as sf:
            sf.write(steering_file_content)
        
        # create steering file: parse source file and merge input_options into it

        SGV_EXECUTABLE_DIR = osp.dirname(self.executable)
        SGV_EXECUTABLE_BNAME = osp.basename(self.executable)
        
        cmd  = f'source $ANALYSIS_PATH/setup_batch.sh && source "{self.sgv_env}"'
        cmd += f' && echo "SRC={input_file} DST={target_path}"'
        cmd += f' && cp -R "{SGV_EXECUTABLE_DIR}/." .'
        cmd += f' && ( [[ -f {self.steering_file_fortran_unit} ]] && rm {self.steering_file_fortran_unit} && echo "Existing steering fortran unit removed" || echo "No existing steering fortran unit removed" )'
        cmd += f' && mv "{self.tmp_steering_name}" "{self.steering_file_fortran_unit}"'
        cmd += f' && ln -s "{input_file}" {self.sgv_input}'
        cmd += f' && echo "Starting SGV at $(date)"'
        cmd += f' && ( ./{SGV_EXECUTABLE_BNAME}'
        cmd += f' && echo "Finished SGV at $(date)"'
        cmd += f' && echo "Moving from worker node to destination"'
        cmd += f' && mv "{self.sgv_output}" "{target_path}"'
        cmd += f' )'
        
        return cmd
    
    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.get_temp_dir(), **kwargs)

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

    def workflow_requires(self):
        reqs = super().workflow_requires()
        configurations.get(str(self.tag)).sgv_requires(self, reqs) # call to inject dynamic workflow requirements
        
        return reqs
    
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))
        
    def create_branch_map(self):
        input_files, input_options = self.sgv_inputs()
        assert(len(input_files) == len(input_options))
        
        return { k: [file, options] for (k, file, options) in zip(
            list(range(len(input_files))),
            input_files,
            input_options
        )}
    
    def output(self):
        # output filename = input filename but extension changed to 'slcio'; necessary for stdhep input
        return self.local_target(f'{osp.splitext(osp.basename(self.branch_data[0]))[0]}.slcio')