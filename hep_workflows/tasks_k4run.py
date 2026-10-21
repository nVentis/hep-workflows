import os.path as osp
import uuid
from abc import ABC
from typing import cast

import law
import luigi

from .framework import BaseWorkflowTask
from .utils import ShellTask
from .utils.types import K4RunBranchValue

# Tasks running a Gaudi steering file via k4run (part of the key4hep stack) on edm4hep files. 
# - AbstractK4Run: runs one k4run job; knows nothing about what the steering file does. Used by
#   the low-level reconstruction after ddsim (tasks_k4run_low_level_reco.py)
# - The high-level reconstruction and the analysis run via k4run, too, but use the same tasks as
#   with Marlin (RecoRuntime/RecoFinal, AnalysisRuntime/AnalysisFinal, see tasks_marlin.py);
#   see AnalysisConfiguration.high_level_reco and AnalysisConfiguration.analysis
#
# Like AbstractDDSim (tasks_sim_full.py), these rely on setup.sh/bootstrap.sh having
# already sourced a key4hep nightly (see $K4H_NIGHTLY); they deliberately don't (re-)source a
# stack themselves since key4hep's nightly setup.sh refuses to run on top of an already
# sourced stack.


def format_cli_arguments(arguments: dict[str, list[str] | str]) -> str:
    """Formats a {arg_name: value(s)} dict into CLI arguments, for AbstractDDSim/
    AbstractK4Run's ddsim_arguments/k4run_arguments - e.g.
    {'physicsList': 'FTFP_BERT'} becomes '--physicsList "FTFP_BERT"',
    {'outputCommands': ['keep *', 'drop Foo']} becomes
    '--outputCommands "keep *" "drop Foo"', and {'trackingOnly': []} becomes a bare
    '--trackingOnly' (a flag that doesn't take a value).
    """

    parts = []
    for key, value in arguments.items():
        if isinstance(value, str):
            parts.append(f'--{key} "{value}"')
        else:
            values = ' '.join(f'"{v}"' for v in value)
            parts.append(f'--{key}' + (f' {values}' if values else ''))

    return ' '.join(parts)


class AbstractK4Run(ABC, ShellTask, BaseWorkflowTask, law.LocalWorkflow):
    """Abstract class for jobs running a Gaudi steering file using k4run (part of
    the key4hep stack) on edm4hep files, producing one edm4hep ROOT file per job.
    Detector-agnostic the same way AbstractDDSim is: steering_file/compact_file
    are obligatory parameters without a built-in default, and additional
    arguments to k4run may be supplied through k4run_arguments.

    What the steering file does is up to the inheriting class; this class only
    - runs `k4run <steering_file> --inputFiles ... --compactFile ... <output_cli()> -n ...`,
      from within the directory of the steering file (e.g. in ILD, it is assumed that the
      steering file is located in the cwd),
    - expects the steering file to write `produced_file` into the (temporary)
      working directory,
    - checks that this file is readable and contains events, and moves it to the
      declared output() together with a small <name>.meta.json timing sidecar
      (which is what the CreateChunks tasks and the index tasks read).

    Branch data (self.branch_data) must be a K4RunBranchValue.

    Like AbstractDDSim, this relies on setup.sh/bootstrap.sh having already
    sourced a key4hep NIGHTLY.
    """

    executable = 'k4run'

    # obligatory - see AbstractDDSim's class docstring for why there's no built-in default
    steering_file:str = cast(str, luigi.Parameter(
        description='Path to the k4run steering script to use, expandvars()-ready.', default=''))
    compact_file:str = cast(str, luigi.Parameter(
        description='Path to the compact detector file to use, expandvars()-ready.', default=''))

    # extra k4run CLI arguments - see format_cli_arguments above. Same task_kwargs override
    # mechanism as steering_file/compact_file, similar to constants/globals in tasks_marlin.py
    k4run_arguments:dict[str, list[str] | str] = {}

    # name of the file the steering file writes into the working directory; this is the
    # file that is checked and moved to the output target
    produced_file:str = 'out.edm4hep.root'

    def get_temp_dir(self):
        output_path = str(self.output().path)
        name = osp.basename(output_path)[:-len('.edm4hep.root')]

        return f'{osp.dirname(output_path)}/TMP-{name}-{str(uuid.uuid4())}'

    def meta_path(self)->str:
        output_path = str(self.output().path)

        return output_path[:-len('.edm4hep.root')] + '.meta.json'

    def output_cli(self)->str:
        """CLI arguments telling the steering file where to write `produced_file`.
        Runs in a subshell after `cd <steering file dir>`, so $OLDPWD is the working directory
        of the job. Override for steering files with a different output convention, and
        use it to append further stage-specific arguments (e.g. a COM energy).
        """
        return f'--outputFile "$OLDPWD/{self.produced_file}"'

    def build_command(self, **kwargs):
        input_files, n_events_max, process, proc_pol, name = cast(K4RunBranchValue, self.branch_data)
        n_events_max = n_events_max if (n_events_max is not None and n_events_max > -1) else -1

        assert self.steering_file, f"steering_file must be set, e.g. via task_kwargs['{self.__class__.__name__}'] on an AnalysisConfiguration"
        assert self.compact_file, f"compact_file must be set, e.g. via task_kwargs['{self.__class__.__name__}'] on an AnalysisConfiguration"

        steering_file = osp.expandvars(self.steering_file)
        steering_file_dir = osp.dirname(steering_file)
        steering_file_name = osp.basename(steering_file)

        target_path = str(self.output().path)
        meta_path = self.meta_path()
        files_arg = ' '.join(f'"{f}"' for f in input_files)
        extra_args = format_cli_arguments(self.k4run_arguments)

        # "branch" is the law branch number, which is what the index tasks use as sample ID
        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s", "branch": %s}'

        cmd  = f'echo "Starting k4run at $(date)" && T_START=$(date +%s)'
        cmd += f' && ( cd "{steering_file_dir}"'
        cmd += f' && k4run "{steering_file_name}"'
        cmd += f' --inputFiles {files_arg}'
        cmd += f' --compactFile "{osp.expandvars(self.compact_file)}"'
        cmd += f' {self.output_cli()}'
        cmd += f' -n {n_events_max}'
        if extra_args:
            cmd += f' {extra_args}'
        cmd += f' )'
        cmd += f' && echo "Finished k4run at $(date)" && T_END=$(date +%s)'
        cmd += f' && echo "Info: Checking produced edm4hep file is readable and contains events"'
        cmd += f' && N_EVT=$(edm4hep_event_counter {self.produced_file}) && [ "$N_EVT" -gt 0 ]'
        cmd += f' && echo "Success: produced file contains ${{N_EVT}} events"'
        cmd += f''' && printf '{meta_fmt}' "$T_START" "$T_END" "$N_EVT" "{process}" "{proc_pol}" "{input_files[0]}" "{self.branch}" > meta.json'''
        cmd += f' && mv "{self.produced_file}" "{target_path}"'
        cmd += f' && mv "meta.json" "{meta_path}"'

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.get_temp_dir(), **kwargs)
