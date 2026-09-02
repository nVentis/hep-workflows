import os.path as osp
import uuid
from abc import ABC
from typing import cast
from collections.abc import Callable

import law
import luigi
import numpy as np
from law.util import flatten

from .framework import HTCondorWorkflow, configurations
from .utils import ShellTask, BaseTask
from .utils.types import DDSimBranchValue, K4RunBranchValue
from .tasks_marlin_chunks import AbstractCreateChunks

# Tasks for running full simulation (ddsim) and reconstruction (k4run)
# Supports any detector for which
# A) a compact file describing the geometry for ddsim exists and which
# B) has reconstruction implemented in Gaudi via k4run.
# Validated for the ILD@FCC-ee detector models (see
# https://github.com/HEP-FCC/FCC-config/blob/main/FCCee/FullSim/ILD_FCCee/README.md)
# and ILD@ILC models
#
# AbstractDDSim/AbstractK4Run's steering_file/compact_file are obligatory, detector-agnostic
# parameters with no built-in default (see their own class docstrings); ddsim_arguments/
# k4run_arguments let you pass extra CLI arguments to either executable, similar to
# constants/globals in tasks_marlin.py. All four are overridable via
# task_kwargs['DDSimBaseJob']/['K4RunBaseJob'] on an AnalysisConfiguration (see MarlinBaseJob
# for the same task_kwargs pattern in tasks_marlin.py).
#
# The intended production chain is:
#   WhizardEventGeneration -> RawIndex -> DDSimRuntime -> CreateDDSimChunks -> DDSimFinal
#       -> K4RunIndex -> K4RunRuntime -> CreateK4RunChunks -> K4RunFinal
#
# mirroring RecoRuntime/CreateRecoChunks/RecoFinal and AnalysisRuntime/CreateAnalysisChunks/
# AnalysisFinal in tasks_marlin.py/tasks_marlin_chunks.py: a small "Runtime" pass measures a
# per-process time-per-event, a "Chunks" task uses that to plan production-sized branches, and
# the "Final" (here: DDSimFinal/K4RunFinal) task processes those branches for real.
#
# Both DDSimFinal and K4RunFinal declare only their single edm4hep output file via
# output() - no AIDA/PfoAnalysis/log directory is kept as part of the task's output, unlike
# the Marlin tasks in tasks_marlin.py (see AbstractDDSim.run()/AbstractK4Run.run(), which run
# in an auto-cleaned temp dir, the same pattern AbstractSGVExternalReadJob/FastSimSGV use).
#
# ddsim/k4run for the ILD@FCC-ee models are currently only validated against key4hep NIGHTLY
# builds, not a dated release - set $K4H_NIGHTLY (see setup.sh/.env) so setup.sh/bootstrap.sh
# sources a nightly instead of (or in addition to, with priority over) a $K4H_RELEASE-based
# release. See AbstractDDSim/AbstractK4Run for why these tasks don't (re-)source a nightly
# stack themselves.


def format_cli_arguments(arguments: dict[str, list[str] | str]) -> str:
    """Formats a {arg_name: value(s)} dict into CLI arguments, for AbstractDDSim/
    AbstractK4Run's ddsim_arguments/k4run_arguments below - e.g.
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


class AbstractDDSim(ABC, ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    """Abstract class for full simulation jobs using ddsim (part of the key4hep
    stack), reading a generator-level LCIO file (e.g. produced by
    WhizardEventGeneration) and writing an edm4hep ROOT file with simulated hits.
    Detector-agnostic within key4hep/DD4hep's reach: steering_file/compact_file
    are the only detector-specific inputs ddsim itself needs, and both are
    obligatory - there's no built-in default (ddsim's steering conventions and
    k4geo's compact file layout both vary per detector implementation, so there's
    nothing generic to fall back to here). Set them, and optionally
    ddsim_arguments, via an AnalysisConfiguration's task_kwargs['DDSimBaseJob'].

    ddsim reads LCIO generator input directly (its own steering file documents
    support for .stdhep, .slcio, .HEPEvt, .hepevt, .hepmc, .pairs), so no LCIO ->
    edm4hep conversion is needed ahead of this step - only the OUTPUT format
    matters for the rest of the chain (see build_command), which is why we
    always write '.edm4hep.root'.

    Full simulation/reconstruction of the ILD@FCC-ee models is currently only
    validated against key4hep NIGHTLY builds, not a dated release - so
    setup.sh/bootstrap.sh must have sourced a nightly (via $K4H_NIGHTLY, taking
    priority over the release-oriented $K4H_RELEASE) before this task's
    build_command runs. We deliberately do NOT (re-)source a nightly stack
    ourselves here: key4hep's nightly setup.sh refuses to source on top of an
    already-sourced stack (`$KEY4HEP_STACK` set - as it always is by the time a
    job's command runs, since setup.sh/bootstrap.sh already sourced one), so
    doing so would just fail with "the Key4hep software stack is already set up".
    """

    executable = 'ddsim'

    # obligatory - see class docstring above; empty by default so .req() calls elsewhere
    # in this file (which don't know about task_kwargs) keep working, but build_command
    # below refuses to run with either left unset
    steering_file:str = cast(str, luigi.Parameter(
        description='Path to the ddsim steering file to use, expandvars()-ready.', default=''))
    compact_file:str = cast(str, luigi.Parameter(
        description='Path to the compact detector file to use, expandvars()-ready.', default=''))

    # extra ddsim CLI arguments - see format_cli_arguments above. Same task_kwargs override
    # mechanism as steering_file/compact_file, similar to constants/globals in tasks_marlin.py
    ddsim_arguments:dict[str, list[str] | str] = {}

    n_events_max:int|None = None
    n_events_skip:int|None = None

    def get_temp_dir(self):
        output_path = str(self.output().path)
        name = osp.basename(output_path)[:-len('.edm4hep.root')]

        return f'{osp.dirname(output_path)}/TMP-{name}-{str(uuid.uuid4())}'

    def meta_path(self)->str:
        output_path = str(self.output().path)

        return output_path[:-len('.edm4hep.root')] + '.meta.json'

    def build_command(self, **kwargs):
        location, n_chunk, n_chunks_in_sample, n_events_skip, n_events_max, process, proc_pol = \
            cast(DDSimBranchValue, self.branch_data)

        assert self.steering_file, "steering_file must be set, e.g. via task_kwargs['DDSimBaseJob'] on an AnalysisConfiguration"
        assert self.compact_file, "compact_file must be set, e.g. via task_kwargs['DDSimBaseJob'] on an AnalysisConfiguration"

        n_events_skip = n_events_skip if (n_events_skip is not None and n_events_skip > -1) else self.n_events_skip
        n_events_max  = n_events_max  if (n_events_max  is not None and n_events_max  > -1) else self.n_events_max
        n_events_max  = n_events_max if n_events_max is not None else -1  # -1: process all events in the input file

        target_path = str(self.output().path)
        meta_path = self.meta_path()

        # {"tStart": <epoch>, "tEnd": <epoch>, "nEvtSum": <n>, "process": ..., "proc_pol": ..., "src": ...}
        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s"}'

        cmd  = f'echo "Starting ddsim at $(date)" && T_START=$(date +%s)'
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
        cmd += f''' && printf '{meta_fmt}' "$T_START" "$T_END" "$N_EVT" "{process}" "{proc_pol}" "{location}" > meta.json'''
        cmd += f' && mv "out.edm4hep.root" "{target_path}"'
        cmd += f' && mv "meta.json" "{meta_path}"'

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.get_temp_dir(), **kwargs)


class DDSimBaseJob(AbstractDDSim):
    """Base class for ddsim jobs. Tasks subclassing this must set `debug`:
    - debug=True (DDSimRuntime): runs on a small subset of RawIndex's samples,
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

        # parameter injection from registered configurations, same mechanism as MarlinBaseJob
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
        sample_bname = osp.splitext(osp.basename(location))[0]

        return f'{sample_bname}.{n_chunk}-{n_chunks_in_sample}-{self.branch}'

    @workflow_condition.output
    def output(self):
        return self.local_target(f'{self.output_name()}.edm4hep.root')

    def workflow_requires(self):
        from .tasks_index import RawIndex

        reqs = {}
        reqs['index_task'] = RawIndex.req(self)
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
    from RawIndex, for a runtime analysis.
    """
    debug = True


class DDSimFinal(DDSimBaseJob):
    """Runs ddsim for the full production, using CreateDDSimChunks' chunk
    plan. Produces one edm4hep ROOT file (SimTrackerHits/SimCalorimeterHits/
    MCParticles/...) per chunk - no other auxiliary files are kept as part of
    this task's output.
    """
    debug = False


class CreateDDSimChunks(AbstractCreateChunks):
    # kept below HTCondorWorkflow.max_runtime's default of 3h (see framework.py) - a jobtime
    # exceeding that plans chunks that can outrun the reserved htcondor runtime, which condor
    # then holds with "Job runtime longer than reserved"
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each ddsim job, in seconds.', default=7200))

    # ddsim/geometry-loading startup overhead, in seconds; subtracted from the measured
    # per-branch runtime before deriving a time-per-event estimate.
    T_STARTUP = 20

    def requires(self):
        from .tasks_index import RawIndex

        return [
            RawIndex.req(self),
            DDSimRuntime.req(self)
        ]

    def run(self):
        from .utils.normalization import get_process_normalization, get_sample_chunk_splits, CHUNK_SPLIT_MODES
        from .utils.runtime_analysis import get_runtime_analysis_from_meta, get_adjusted_time_per_event

        inputs = self.input()
        processes = np.load(inputs[0][0].path)
        samples = np.load(inputs[0][1].path)

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
                    custom_statistics=self.custom_statistics(), split_mode=CHUNK_SPLIT_MODES['ONE_TO_MANY'])

        self.save_chunk_outputs(chunks, runtime_analysis, time_per_event, process_normalization)


class K4RunIndex(BaseTask):
    """Builds a samples.npy/processes.npy pair matching AbstractIndex/
    ProcessIndex's shape, but describing DDSimFinal's ACTUAL, factual output
    rather than raw LCIO input - analogous to how AnalysisIndex re-indexes
    RecoFinal's real output rather than trusting CreateRecoChunks' plan.

    Unlike AbstractIndex (which recovers sample metadata from LCIO event/run
    parameters via pyLCIO - the only way to learn what's inside an arbitrary
    LCIO file), edm4hep files produced by ddsim don't carry the same
    physics-process bookkeeping (crossSection, processName, ...) that Whizard
    writes into LCIO. We therefore recover that metadata from
    CreateDDSimChunks' own chunk plan (which already records, for every
    branch, which process/proc_pol/sample id it belongs to - DDSimFinal's
    branch numbering is identical to that plan, see
    DDSimBaseJob.create_branch_map), and only use edm4hep_event_count() to
    learn the real number of produced events per branch.

    processes.npy is carried over unchanged from RawIndex, since cross-section/
    process-level information does not change between the generator and
    simulation stages.
    """

    overview:bool = cast(bool, luigi.BoolParameter(
        description='Whether or not to force showing the overview when the task' +
        ' is already done.',
        default=False))

    def requires(self):
        from .tasks_index import RawIndex

        return {
            'raw_index': RawIndex.req(self),
            'sim_chunks': CreateDDSimChunks.req(self),
            'full_sim': DDSimFinal.req(self),
        }

    def output(self):
        return [
            self.local_target('processes.npy'),
            self.local_target('samples.npy'),
            self.local_target('processes.csv'),
            self.local_target('samples.csv'),
        ]

    def run(self):
        from .utils.edm4hep import edm4hep_event_count
        from .utils.ProcessIndex import ProcessIndex

        inputs = self.input()
        processes = np.load(inputs['raw_index'][0].path)
        raw_samples = np.load(inputs['raw_index'][1].path)
        chunks = np.load(inputs['sim_chunks'][0].path)
        sim_collection = inputs['full_sim']['collection']

        rows = []
        for branch in chunks['branch'].tolist():
            row = chunks[chunks['branch'] == branch][0]
            location = str(sim_collection[branch].path)
            n_events = edm4hep_event_count(location)
            src_sample = raw_samples[raw_samples['sid'] == row['sid']][0]

            rows.append((
                branch, int(src_sample['run_id']), str(row['process']), str(row['proc_pol']),
                n_events, int(src_sample['pol_e']), int(src_sample['pol_p']), location, 'MCParticles'
            ))

        samples = np.array(rows, dtype=ProcessIndex.dtype_sample)

        BaseTask.touch_parent(self.output()[0])
        np.save(str(self.output()[0].path), processes)
        np.save(str(self.output()[1].path), samples)
        np.savetxt(str(self.output()[2].path), processes, delimiter=',', fmt='%s', header=','.join(processes.dtype.names))
        np.savetxt(str(self.output()[3].path), samples, delimiter=',', fmt='%s', header=','.join(samples.dtype.names))

        self.publish_message(f'Indexed {len(samples)} DDSimFinal output samples')
        self.printOverview()

    def printOverview(self):
        from law.util import colored
        from .utils.task_overviews import index_overview

        processes = np.load(str(self.output()[0].path))
        samples = np.load(str(self.output()[1].path))

        self.publish_message(colored(index_overview(samples, processes, self), color='green', background='black'))

    def complete(self):
        complete = super().complete()

        if complete and self.overview:
            self.printOverview()

        return complete


class AbstractK4Run(ABC, ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    """Abstract class for reconstruction jobs using k4run (part of the key4hep
    stack) on edm4hep files produced by DDSimFinal, running the standard ILD
    reconstruction chain (tracking, calorimeter digitisation and PandoraPFA),
    producing an edm4hep ROOT file that includes a PandoraPFOs collection -
    analogous to FastSimSGV's output, but from full simulation/reconstruction
    rather than SGV's parametrized fast simulation. Detector-agnostic the same
    way AbstractDDSim is - see steering_file/compact_file there.

    Runs Gaudi-based reconstruction using k4run
    Requires a steering_file and a compact file describing detector geometry
    Additional arguments to k4run may be supplied through k4run_arguments.

    Like AbstractDDSim, this relies on setup.sh/bootstrap.sh having already
    sourced a key4hep NIGHTLY
    """

    executable = 'k4run'

    # obligatory - see AbstractDDSim's class docstring for why there's no built-in default
    steering_file:str = cast(str, luigi.Parameter(
        description='Path to the k4run reconstruction steering script to use, expandvars()-ready.', default=''))
    compact_file:str = cast(str, luigi.Parameter(
        description='Path to the compact detector file to use, expandvars()-ready.', default=''))

    # extra k4run CLI arguments - see format_cli_arguments above. Same task_kwargs override
    # mechanism as steering_file/compact_file, similar to constants/globals in tasks_marlin.py
    k4run_arguments:dict[str, list[str] | str] = {}

    # ILDConfig's Config/Parameters<E>GeV.cfg (and therefore ILDReconstruction.py's
    # --cmsEnergy) only exist for a handful of values; pick whichever is closest to the
    # configuration's actual sqrt_s
    cms_energy:int = 500

    def get_temp_dir(self):
        output_path = str(self.output().path)
        name = osp.basename(output_path)[:-len('.edm4hep.root')]

        return f'{osp.dirname(output_path)}/TMP-{name}-{str(uuid.uuid4())}'

    def meta_path(self)->str:
        output_path = str(self.output().path)

        return output_path[:-len('.edm4hep.root')] + '.meta.json'

    def build_command(self, **kwargs):
        input_files, n_events_max, process, proc_pol, name = cast(K4RunBranchValue, self.branch_data)
        n_events_max = n_events_max if (n_events_max is not None and n_events_max > -1) else -1

        assert self.steering_file, "steering_file must be set, e.g. via task_kwargs['K4RunBaseJob'] on an AnalysisConfiguration"
        assert self.compact_file, "compact_file must be set, e.g. via task_kwargs['K4RunBaseJob'] on an AnalysisConfiguration"

        target_path = str(self.output().path)
        meta_path = self.meta_path()
        files_arg = ' '.join(f'"{f}"' for f in input_files)
        extra_args = format_cli_arguments(self.k4run_arguments)

        meta_fmt = '{"tStart": %s, "tEnd": %s, "nEvtSum": %s, "process": "%s", "proc_pol": "%s", "src": "%s"}'

        # ILDReconstruction.py imports Calibration/Config/Tracking/... files from
        # $ILD_CONFIG_DIR/StandardConfig/production by relative path, so that must be cwd
        cmd  = f'echo "Starting k4run at $(date)" && T_START=$(date +%s)'
        cmd += f' && ( cd "{osp.expandvars("$ILD_CONFIG_DIR/StandardConfig/production")}"'
        cmd += f' && k4run "{osp.expandvars(self.steering_file)}"'
        cmd += f' --inputFiles {files_arg}'
        cmd += f' --compactFile "{osp.expandvars(self.compact_file)}"'
        # ILDReconstruction.py appends _REC.edm4hep.root/_AIDA.root/_PfoAnalysis.root to
        # outputFileBase itself; --lcioOutput off skips its (unused, discarded like the
        # AIDA/PfoAnalysis files below) additional LCIO-format output
        cmd += f' --outputFileBase "$OLDPWD/out"'
        cmd += f' --lcioOutput off'
        cmd += f' --cmsEnergy {self.cms_energy}'
        cmd += f' -n {n_events_max}'
        if extra_args:
            cmd += f' {extra_args}'
        cmd += f' )'
        cmd += f' && echo "Finished k4run at $(date)" && T_END=$(date +%s)'
        cmd += f' && echo "Info: Checking produced edm4hep file is readable and contains events"'
        cmd += f' && N_EVT=$(edm4hep_event_counter out_REC.edm4hep.root) && [ "$N_EVT" -gt 0 ]'
        cmd += f' && echo "Success: produced file contains ${{N_EVT}} events"'
        cmd += f''' && printf '{meta_fmt}' "$T_START" "$T_END" "$N_EVT" "{process}" "{proc_pol}" "{input_files[0]}" > meta.json'''
        cmd += f' && mv "out_REC.edm4hep.root" "{target_path}"'
        cmd += f' && mv "meta.json" "{meta_path}"'

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.get_temp_dir(), **kwargs)


class K4RunBaseJob(AbstractK4Run):
    """Base class for k4run reconstruction jobs. Tasks subclassing this must
    set `debug`:
    - debug=True (K4RunRuntime): runs on a small subset of K4RunIndex's
      samples, capped at debug_n_events_max events each, for a runtime
      analysis
    - debug=False (K4RunFinal): runs over CreateK4RunChunks' (grouped)
      chunk plan
    """
    debug = True

    debug_n_files_to_process:int|None = 3
    # cap the runtime-measurement pass to a modest number of events so that timing a
    # single (potentially huge, full-energy ILD@FCC-ee) sample doesn't itself take as
    # long as a production job would; unlike DDSimRuntime's debug_n_events_skip, there
    # is no skip here - k4run's event count cap alone is enough for a quick timing sample,
    # and any startup/geometry-loading overhead is instead removed via the usual T0
    # correction (see CreateK4RunChunks.T_STARTUP and get_adjusted_time_per_event)
    debug_n_events_max:int = 50

    def pre_run_command(self, **kwargs):
        config = configurations.get(str(self.tag))

        if 'K4RunBaseJob' in config.task_kwargs:
            for prop, value in (
                    config.task_kwargs['K4RunBaseJob'](self) if isinstance(config.task_kwargs['K4RunBaseJob'], Callable) else \
                    config.task_kwargs['K4RunBaseJob']).items():
                setattr(self, prop, value)

    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return all(cast(law.FileSystemTarget, elem).exists() for elem in flatten(self.input()))

    @workflow_condition.create_branch_map
    def create_branch_map(self) -> dict[int, K4RunBranchValue]:
        branch_map:dict[int, K4RunBranchValue] = {}

        config = configurations.get(str(self.tag))
        if 'K4RunBaseJob' in config.task_kwargs:
            for prop, value in (
                    config.task_kwargs['K4RunBaseJob'](self) if isinstance(config.task_kwargs['K4RunBaseJob'], Callable) else \
                    config.task_kwargs['K4RunBaseJob']).items():
                setattr(self, prop, value)

        samples = np.load(self.input()['index_task'][1].path)

        if not self.debug:
            # the calculated (grouped many-to-many) chunking is used: every branch reads
            # one or more whole DDSimFinal output files as one concatenated event stream
            chunks = np.load(self.input()['reco_chunks'][0].path)

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

    def workflow_requires(self):
        reqs = {}
        reqs['index_task'] = K4RunIndex.req(self)
        # K4RunFinal/K4RunRuntime always need DDSimFinal to have fully completed -
        # not just for K4RunIndex's samples.npy, but because that samples.npy references
        # DDSimFinal's own produced files as input
        reqs['full_sim'] = DDSimFinal.req(self)
        if not self.debug:
            reqs['reco_chunks'] = CreateK4RunChunks.req(self)

        return reqs


class K4RunRuntime(K4RunBaseJob):
    """Runs the ILD reconstruction chain via k4run on a small subset of
    DDSimFinal's output, for a runtime analysis.
    """
    debug = True


class K4RunFinal(K4RunBaseJob):
    """Runs the ILD reconstruction chain via k4run for the full production,
    using CreateK4RunChunks' chunk plan. Produces one edm4hep ROOT file
    (including a PandoraPFOs collection) per chunk - no other auxiliary files
    are kept as part of this task's output. Requires DDSimFinal.
    """
    debug = False


class CreateK4RunChunks(AbstractCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each k4run job, in seconds.', default=3600))

    # k4run/geometry-loading startup overhead, in seconds
    T_STARTUP = 20

    def requires(self):
        return [
            K4RunIndex.req(self),
            K4RunRuntime.req(self),
            CreateDDSimChunks.req(self)
        ]

    def run(self):
        from .utils.normalization import get_process_normalization, get_sample_chunk_splits, construct_sample_groups, CHUNK_SPLIT_MODES
        from .utils.runtime_analysis import get_runtime_analysis_from_meta, get_adjusted_time_per_event

        inputs = self.input()
        processes = np.load(inputs[0][0].path)
        full_sim_samples = np.load(inputs[0][1].path)
        sim_chunks = np.load(inputs[2][0].path)

        # groups DDSimFinal's per-source-file chunks back together by originating
        # sample, mirroring how CreateAnalysisChunks groups RecoFinal's chunked output
        # for the Analysis stage (see construct_sample_groups/get_sample_chunk_splits_m2m_grouped)
        sample_groups = construct_sample_groups(sim_chunks, full_sim_samples)

        runtime_collection = inputs[1]['collection']
        meta_paths = {}
        for i in range(len(runtime_collection)):
            path = str(runtime_collection[i].path)
            meta_paths[i] = path[:-len('.edm4hep.root')] + '.meta.json'

        runtime_analysis = get_runtime_analysis_from_meta(meta_paths)
        process_normalization = get_process_normalization(processes, full_sim_samples, RATIO_BY_TOTAL=self.fraction)
        time_per_event = get_adjusted_time_per_event(runtime_analysis, T0=self.T_STARTUP)

        chunks = get_sample_chunk_splits(full_sim_samples, process_normalization=process_normalization,
                    adjusted_time_per_event=time_per_event, MAXIMUM_TIME_PER_JOB=cast(int, self.jobtime),
                    custom_statistics=self.custom_statistics(), sample_groups=sample_groups,
                    split_mode=CHUNK_SPLIT_MODES['MANY_TO_MANY'])

        self.save_chunk_outputs(chunks, runtime_analysis, time_per_event, process_normalization)
