import os.path as osp
from abc import ABC
from typing import cast
from collections.abc import Callable

import law
import luigi
import numpy as np
from law.util import flatten

from .framework import BaseWorkflowTask, configurations
from .utils import ShellTask
from .utils.filenames import splitext_mod
from .utils.types import DDSimBranchValue

def format_cli_arguments(arguments: dict[str, list[str] | str]) -> str:
    """Formats a {arg_name: value(s)} dict into CLI arguments, for AbstractDDSim's
    ddsim_arguments - e.g. {'physicsList': 'FTFP_BERT'} becomes '--physicsList "FTFP_BERT"',
    {'outputCommands': ['keep *', 'drop Foo']} becomes '--outputCommands "keep *" "drop Foo"',
    and {'trackingOnly': []} becomes a bare '--trackingOnly' (a flag that doesn't take a value).
    """

    parts = []
    for key, value in arguments.items():
        if isinstance(value, str):
            parts.append(f'--{key} "{value}"')
        else:
            values = ' '.join(f'"{v}"' for v in value)
            parts.append(f'--{key}' + (f' {values}' if values else ''))

    return ' '.join(parts)


class AbstractDDSim(ABC, ShellTask, BaseWorkflowTask, law.LocalWorkflow):
    """Abstract class for full simulation jobs using ddsim, reading a generator-
    level LCIO file (e.g. produced by WhizardEventGeneration) and writing an
    edm4hep ROOT file with simulated hits.
    
    Detector-agnostic within key4hep/DD4hep's reach: steering_file/compact_file
    are the only detector-specific inputs ddsim itself needs, and both are
    obligatory - there's no built-in default (ddsim's steering conventions and
    k4geo's compact file layout both vary per detector implementation, so there's
    nothing generic to fall back to here). Set them, and optionally
    ddsim_arguments, via an AnalysisConfiguration's task_kwargs['DDSimBaseJob'].

    ddsim reads LCIO generator input directly (it also supports .stdhep, .HEPEvt,
    .hepevt, .hepmc, .pairs), so no conversion is needed to edm4hep. Only the
    OUTPUT format matters for the rest of the chain (see build_command), which is
    why we always write '.edm4hep.root'.

    Full simulation/reconstruction of the models validated so far (ILD@FCC-ee) is currently only
    validated against key4hep NIGHTLY builds, not a dated release - so
    setup.sh/bootstrap.sh must have sourced a nightly (via $K4H_NIGHTLY, taking
    priority over the release-oriented $K4H_RELEASE) before this task's
    build_command runs. We deliberately do NOT (re-)source a nightly stack
    ourselves here, as key4hep's nightly setup.sh refuses to source on top of an
    already-sourced stack
    """

    executable = 'ddsim'

    # obligatory - see class docstring above; empty by default so .req() calls elsewhere
    # in this file (which don't know about task_kwargs) keep working, but build_command
    # below refuses to run with either left unset
    steering_file:str = cast(str, luigi.Parameter(
        description='Path to the ddsim steering file to use, expandvars()-ready.', default=''))
    compact_file:str = cast(str, luigi.Parameter(
        description='Path to the compact detector file to use, expandvars()-ready.', default=''))

    # extra ddsim CLI arguments - see format_cli_arguments. Same task_kwargs override
    # mechanism as steering_file/compact_file, similar to constants/globals in tasks_reco_ana.py
    ddsim_arguments:dict[str, list[str] | str] = {}

    n_events_max:int|None = None
    n_events_skip:int|None = None

    def get_temp_dir(self):
        return f'{self.htcondor_output_directory().path}/TMP-{self.output_name()}'

    def build_command(self, **kwargs):
        location, n_chunk, n_chunks_in_sample, n_events_skip, n_events_max, process, proc_pol = \
            cast(DDSimBranchValue, self.branch_data)

        assert self.steering_file, "steering_file must be set, e.g. via task_kwargs['DDSimBaseJob'] on an AnalysisConfiguration"
        assert self.compact_file, "compact_file must be set, e.g. via task_kwargs['DDSimBaseJob'] on an AnalysisConfiguration"

        n_events_skip = n_events_skip if (n_events_skip is not None and n_events_skip > -1) else self.n_events_skip
        n_events_max  = n_events_max  if (n_events_max  is not None and n_events_max  > -1) else self.n_events_max
        n_events_max  = n_events_max if n_events_max is not None else -1  # -1: process all events in the input file

        output_dir, output_file = self.output()
        temp = self.get_temp_dir()

        # same sidecar as written by the tasks in tasks_reco_ana.py
        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s", "branch": %s}'

        cmd  = f'echo "Starting ddsim at $(date)" && T_START=$(date +%s)'
        cmd += f' && rm -rf {self.htcondor_output_directory().path}/*-{str(self.branch)}'
        cmd += f' && mkdir -p "{temp}" && cd "{temp}"'
        cmd += f' && ddsim'
        cmd += f' --steeringFile "{osp.expandvars(self.steering_file)}"'
        cmd += f' --compactFile "{osp.expandvars(self.compact_file)}"'
        cmd += f' --inputFiles "{location}"'
        cmd += f' --outputFile "out.edm4hep.root"'
        cmd += f' --numberOfEvents {n_events_max}'
        if n_events_skip is not None and n_events_skip > 0:
            cmd += f' --skipNEvents {n_events_skip}'
        extra_args = format_cli_arguments(self.ddsim_arguments)
        if extra_args:
            cmd += f' {extra_args}'
        cmd += f' && echo "Finished ddsim at $(date)" && T_END=$(date +%s)'
        cmd += f' && echo "Info: Checking produced edm4hep file is readable and contains events"'
        cmd += f' && N_EVT=$(edm4hep_event_counter out.edm4hep.root) && [ "$N_EVT" -gt 0 ]'
        cmd += f' && echo "Success: produced file contains ${{N_EVT}} events"'
        cmd += f''' && printf '{meta_fmt}' "$T_START" "$T_END" "$N_EVT" "{process}" "{proc_pol}" "{location}" "{self.branch}" > meta.json'''
        cmd += f' && mv "out.edm4hep.root" "{output_file.path}" && cd .. && mv "{temp}" "{output_dir.path}"'

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, keep_cwd=True, **kwargs)


class DDSimBaseJob(AbstractDDSim):
    """Base class for ddsim jobs. Tasks subclassing this must set `debug`:
    - debug=True (DDSimRuntime): runs on a small subset of GeneratorIndex's samples,
      capped at debug_n_events_max events each, for a runtime analysis
    - debug=False (DDSimFinal): runs over CreateDDSimChunks' chunk plan
    """
    debug = True

    # controls how many files are processed in debug mode, per proc_pol
    # if None, all files are processed
    debug_n_files_to_process:int|None = 3
    
    # cap the runtime-measurement pass so timing a single sample doesn't
    # itself take as long as a production job would
    debug_n_events_max:int|None = 20
    debug_n_events_skip:int = 0

    def pre_run_command(self, **kwargs):
        config = configurations.get(str(self.tag))

        if 'DDSimBaseJob' in config.task_kwargs:
            for prop, value in (
                    config.task_kwargs['DDSimBaseJob'](self) if isinstance(config.task_kwargs['DDSimBaseJob'], Callable) else \
                    config.task_kwargs['DDSimBaseJob']).items():
                setattr(self, prop, value)

    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))

    @workflow_condition.create_branch_map
    def create_branch_map(self) -> dict[int, DDSimBranchValue]:
        branch_map:dict[int, DDSimBranchValue] = {}

        # parameter injection from registered configurations, same mechanism as RecoAnaBaseJob
        config = configurations.get(str(self.tag))
        if 'DDSimBaseJob' in config.task_kwargs:
            for prop, value in (
                    config.task_kwargs['DDSimBaseJob'](self) if isinstance(config.task_kwargs['DDSimBaseJob'], Callable) else \
                    config.task_kwargs['DDSimBaseJob']).items():
                setattr(self, prop, value)

        samples = np.load(self.input()['index_task'][1].path)

        if not self.debug:
            # the calculated chunking (ONE_TO_MANY, single input file per branch) is used
            chunks = np.load(self.input()['sim_chunks'][0].path)

            for branch in chunks['branch'].tolist():
                row = chunks[chunks['branch'] == branch][0]

                branch_map[branch] = (
                    str(row['location']), int(row['n_chunk_in_sample']), int(row['n_chunks_in_sample']),
                    int(row['chunk_start']), int(row['chunk_size']),
                    str(row['process']), str(row['proc_pol'])
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
                    branch_map[i] = (
                        str(entry['location']), 0, 1,
                        self.debug_n_events_skip,
                        self.debug_n_events_max if self.debug_n_events_max is not None else -1,
                        str(entry['process']), str(entry['proc_pol'])
                    )
                    i += 1

        return branch_map

    def output_name(self):
        location, n_chunk, n_chunks_in_sample = cast(DDSimBranchValue, self.branch_data)[:3]
        sample_bname = splitext_mod(osp.basename(location))[0]

        return f'{sample_bname}.{n_chunk}-{n_chunks_in_sample}-{self.branch}'

    @workflow_condition.output
    def output(self):
        # a directory holding everything the job produced (e.g. meta.json) and the edm4hep file
        return [
            self.local_directory_target(self.output_name()),
            self.local_target(f'{self.output_name()}.edm4hep.root')
        ]

    def workflow_requires(self):
        from .tasks_index import GeneratorIndex
        from .tasks_chunks import CreateDDSimChunks

        reqs = {}
        reqs['index_task'] = GeneratorIndex.req(self)
        if not self.debug:
            reqs['sim_chunks'] = CreateDDSimChunks.req(self)

        # inject dynamic workflow requirements from the registered configuration
        configurations.get(str(self.tag)).task_requires(self, reqs)

        return reqs

    def requires(self):
        # branch-level mirror of workflow_requires() so the dynamic
        # workflow_condition evaluates identically whether it is called on the
        # workflow or on a branch task (self.input() otherwise resolves to an
        # empty dict on branches -> all([]) == True -> condition wrongly "met")
        return self.workflow_requires()


class DDSimRuntime(DDSimBaseJob):
    """Runs ddsim on a small subset of the raw (generator-level) LCIO samples
    from GeneratorIndex, for a runtime analysis.
    """
    debug = True


class DDSimFinal(DDSimBaseJob):
    """Runs ddsim for the full production, using CreateDDSimChunks' chunk
    plan. Produces one edm4hep ROOT file (SimTrackerHits/SimCalorimeterHits/
    MCParticles/...) and one directory (with meta.json) per chunk.
    """
    debug = False
