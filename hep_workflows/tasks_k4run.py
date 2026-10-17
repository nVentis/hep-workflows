import os.path as osp
import uuid
from abc import ABC, abstractmethod
from typing import cast
from collections.abc import Callable

import law
import luigi
import numpy as np
from law.util import flatten

from .framework import BaseWorkflowTask, configurations
from .utils import ShellTask
from .utils.types import K4RunBranchValue
from .tasks_marlin_chunks import AbstractCreateChunks

# Generic building blocks for all tasks running Gaudi steering files via k4run (part of the
# key4hep stack):
# - AbstractK4Run: runs one k4run job; knows nothing about what the steering file does
# - AbstractK4RunChunkedJob: a k4run stage that consumes an index (samples.npy) and, for
#   production runs, a chunk plan (chunks.npy) - i.e. the "Runtime"/"Final" pairs
# - AbstractK4RunCreateChunks: the matching chunk planner
#
# The concrete stages live in
# - tasks_k4run_low_level_reco.py: ddsim output -> tracking/calo digitisation/PandoraPFA
# - tasks_k4run_high_level_reco.py: low-level reco output -> FastJet, isolated lepton/photon ID...
# - tasks_k4run_analysis.py: channel-specific analysis on the high-level reco output
#
# Like AbstractDDSim (tasks_sim_full.py), all of these rely on setup.sh/bootstrap.sh having
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
      either from within the directory of the steering file (run_in_steering_dir; for
      steering files that import relative to their cwd) or from the
      temporary working directory of the job,
    - expects the steering file to write `produced_file` into the (temporary)
      working directory,
    - checks that this file is readable and contains events, and moves it to the
      declared output() together with a small <name>.meta.json timing sidecar
      (which is what the CreateChunks tasks and the index tasks read). Further files
      of the working directory listed in extra_output_files are kept as
      <output name>.<file name> next to the output.

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

    # further files written by the steering file into the working directory that should be
    # kept (e.g. ROOT files with analysis ntuples); stored next to the output as <output name>.<file name>
    extra_output_files:list[str] = []

    # whether k4run is run from the directory of the steering file (instead of the temporary
    # working directory of the job). Needed by steering files importing relative to their cwd
    # (e.g. ILDConfig's ILDReconstruction.py). If False, files written by the steering file
    # with a relative path end up in the working directory of the job
    run_in_steering_dir:bool = True

    def get_temp_dir(self):
        output_path = str(self.output().path)
        name = osp.basename(output_path)[:-len('.edm4hep.root')]

        return f'{osp.dirname(output_path)}/TMP-{name}-{str(uuid.uuid4())}'

    def meta_path(self)->str:
        output_path = str(self.output().path)

        return output_path[:-len('.edm4hep.root')] + '.meta.json'

    def output_cli(self)->str:
        """CLI arguments telling the steering file where to write `produced_file`.
        Runs in a subshell, optionally after `cd <steering file dir>` (see run_in_steering_dir),
        so job_dir_ref() is the working directory of the job. Override for steering files
        with a different output convention, and use it to append further stage-specific
        arguments (e.g. a COM energy).
        """
        return f'--outputFile "{self.job_dir_ref()}/{self.produced_file}"'

    def job_dir_ref(self)->str:
        """Shell expression for the temporary working directory of the job, valid in the subshell running k4run"""
        return '$OLDPWD' if self.run_in_steering_dir else '$PWD'

    def build_command(self, **kwargs):
        input_files, n_events_max, process, proc_pol, name = cast(K4RunBranchValue, self.branch_data)
        n_events_max = n_events_max if (n_events_max is not None and n_events_max > -1) else -1

        assert self.steering_file, f"steering_file must be set, e.g. via task_kwargs['{self.__class__.__name__}'] on an AnalysisConfiguration"
        assert self.compact_file, f"compact_file must be set, e.g. via task_kwargs['{self.__class__.__name__}'] on an AnalysisConfiguration"

        steering_file = osp.expandvars(self.steering_file)
        steering_file_dir = osp.dirname(steering_file)
        steering_file_name = osp.basename(steering_file)

        target_path = str(self.output().path)
        target_base = target_path[:-len('.edm4hep.root')]
        meta_path = self.meta_path()
        files_arg = ' '.join(f'"{f}"' for f in input_files)
        extra_args = format_cli_arguments(self.k4run_arguments)

        # "branch" is the law branch number, which is what the index tasks use as sample ID
        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s", "branch": %s}'

        cmd  = f'echo "Starting k4run at $(date)" && T_START=$(date +%s)'
        if self.run_in_steering_dir:
            cmd += f' && ( cd "{steering_file_dir}"'
            cmd += f' && k4run "{steering_file_name}"'
        else:
            cmd += f' && ( k4run "{steering_file}"'
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
        for extra_file in self.extra_output_files:
            cmd += f' && mv "{extra_file}" "{target_base}.{extra_file}"'
        cmd += f' && mv "meta.json" "{meta_path}"'

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.get_temp_dir(), **kwargs)


class AbstractK4RunChunkedJob(AbstractK4Run):
    """Base class for k4run stages working on an index of edm4hep samples. Tasks
    subclassing this must set `debug`:
    - debug=True (*Runtime jobs): runs on a small subset of the index task's
      samples, capped at debug_n_events_max events each, for a runtime
      analysis
    - debug=False (*Final jobs): runs over the stage's CreateChunks (grouped)
      chunk plan

    Inheriting classes must define
    - task_kwargs_key: the key in AnalysisConfiguration.task_kwargs under which
      parameters (steering_file, compact_file, k4run_arguments, ...) are injected
    - workflow_requires(), which must return
        - 'index_task': task subclassing AbstractIndex
        - 'k4run_chunks': task subclassing AbstractK4RunCreateChunks, only
            required if self.debug is False
    """
    debug = True

    task_kwargs_key:str

    debug_n_files_to_process:int|None = 3
    # cap the runtime-measurement pass to a modest number of events so that timing a
    # single (potentially huge, full-energy) sample doesn't itself take as long as a
    # production job would; unlike DDSimRuntime's debug_n_events_skip, there is no skip
    # here - k4run's event count cap alone is enough for a quick timing sample, and any
    # startup/geometry-loading overhead is instead removed via the usual T0 correction
    # (see AbstractK4RunCreateChunks.T_STARTUP and get_adjusted_time_per_event)
    debug_n_events_max:int = 50

    def inject_task_kwargs(self):
        """Parameter injection from registered configurations, same mechanism as MarlinBaseJob"""
        config = configurations.get(str(self.tag))

        if self.task_kwargs_key in config.task_kwargs:
            task_kwargs = config.task_kwargs[self.task_kwargs_key]

            for prop, value in (task_kwargs(self) if isinstance(task_kwargs, Callable) else task_kwargs).items():
                setattr(self, prop, value)

    def pre_run_command(self, **kwargs):
        self.inject_task_kwargs()

    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))

    @workflow_condition.create_branch_map
    def create_branch_map(self) -> dict[int, K4RunBranchValue]:
        branch_map:dict[int, K4RunBranchValue] = {}

        self.inject_task_kwargs()

        samples = np.load(self.input()['index_task'][1].path)

        if not self.debug:
            # the calculated (grouped many-to-many) chunking is used: every branch reads
            # one or more whole files of the previous stage as one concatenated event stream
            chunks = np.load(self.input()['k4run_chunks'][0].path)

            for branch in np.unique(chunks['branch']).tolist():
                c_chunks = chunks[chunks['branch'] == branch]
                files = list(c_chunks['location'])
                src_bname = str(c_chunks['src_bname'][0])

                branch_map[branch] = (
                    files, -1,
                    str(c_chunks['process'][0]), str(c_chunks['proc_pol'][0]),
                    f'{src_bname}.{branch}'
                )
        else:
            # a debug run: debug_n_files_to_process files per proc_pol, capped at
            # debug_n_events_max events each
            selection = samples[np.lexsort((samples['location'], samples['proc_pol']))]

            i = 0
            for proc_pol in np.unique(selection['proc_pol']):
                items = selection[selection['proc_pol'] == proc_pol]
                if self.debug_n_files_to_process is not None and self.debug_n_files_to_process > 0:
                    items = items[:self.debug_n_files_to_process]

                for entry in items:
                    location = str(entry['location'])
                    name = f'{osp.splitext(osp.basename(location))[0]}.{i}'

                    branch_map[i] = (
                        [location], self.debug_n_events_max,
                        str(entry['process']), str(entry['proc_pol']),
                        name
                    )
                    i += 1

        return branch_map

    def output_name(self):
        return cast(K4RunBranchValue, self.branch_data)[4]

    @workflow_condition.output
    def output(self):
        return self.local_target(f'{self.output_name()}.edm4hep.root')

    @abstractmethod
    def workflow_requires(self):
        pass

    def requires(self):
        return self.workflow_requires()


class AbstractK4RunCreateChunks(AbstractCreateChunks):
    """Chunk planner for a stage derived from AbstractK4RunChunkedJob. requires()
    must return a list of three tasks:
    - the index task describing the stage's input samples
    - the stage's *Runtime task, for the runtime analysis (via its meta.json sidecars)
    - the CreateChunks task of the stage producing these samples; its (grouped)
      chunk plan is used to merge the per-file output of that stage back together by
      originating source file (a MANY_TO_MANY split), see sample_groups()
    """

    # every stage has its own default jobtime; don't let a downstream CreateChunks task's
    # jobtime leak into the CreateChunks tasks it requires (which law's req() would do for
    # parameters of the same name)
    exclude_params_req_get = {'jobtime'}

    def sample_groups(self, upstream_chunks:np.ndarray, samples:np.ndarray)->dict[str, dict[str, list[int]]]:
        """Default: the previous stage was itself a grouped k4run stage, i.e. one of
        its output files per branch (whose number is the sample ID)"""
        from .utils.normalization import construct_sample_groups_from_grouped_chunks

        return construct_sample_groups_from_grouped_chunks(upstream_chunks, samples)

    def run(self):
        from .utils.normalization import get_process_normalization, get_sample_chunk_splits, CHUNK_SPLIT_MODES
        from .utils.runtime_analysis import get_runtime_analysis_from_meta, get_adjusted_time_per_event

        inputs = self.input()
        processes = np.load(inputs[0][0].path)
        samples = np.load(inputs[0][1].path)
        upstream_chunks = np.load(inputs[2][0].path)

        sample_groups = self.sample_groups(upstream_chunks, samples)

        runtime_collection = inputs[1]['collection']
        meta_paths = {}
        for i in range(len(runtime_collection)):
            path = str(runtime_collection[i].path)
            meta_paths[i] = path[:-len('.edm4hep.root')] + '.meta.json'

        runtime_analysis = get_runtime_analysis_from_meta(meta_paths)
        process_normalization = get_process_normalization(processes, samples, RATIO_BY_TOTAL=self.fraction)
        time_per_event = get_adjusted_time_per_event(runtime_analysis, T0=self.T_STARTUP)

        chunks = get_sample_chunk_splits(samples, process_normalization=process_normalization,
                    adjusted_time_per_event=time_per_event, MAXIMUM_TIME_PER_JOB=cast(int, self.jobtime),
                    custom_statistics=self.custom_statistics(), sample_groups=sample_groups,
                    split_mode=CHUNK_SPLIT_MODES['MANY_TO_MANY'])

        self.save_chunk_outputs(chunks, runtime_analysis, time_per_event, process_normalization)
