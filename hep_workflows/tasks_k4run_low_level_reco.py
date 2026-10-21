import os.path as osp
from typing import cast
from collections.abc import Callable

import law
import luigi
import numpy as np
from law.util import flatten

from .framework import configurations
from .utils import BaseTask
from .utils.types import K4RunBranchValue
from .tasks_sim_full import DDSimFinal, CreateDDSimChunks
from .tasks_k4run import AbstractK4Run
from .tasks_marlin_chunks import AbstractCreateChunks

# Low-level reconstruction (tracking, calo digitisation, PandoraPFA) of the full simulation
# output (DDSimFinal) via k4run. The intended production chain is
#
#   ... -> DDSimRuntime -> CreateDDSimChunks -> DDSimFinal
#       -> K4RunLowLevelRecoIndex -> K4RunLowLevelRecoRuntime -> K4RunLowLevelRecoCreateChunks
#       -> K4RunLowLevelRecoFinal
#
# mirroring RecoRuntime/CreateRecoChunks/RecoFinal and AnalysisRuntime/CreateAnalysisChunks/
# AnalysisFinal in tasks_marlin.py/tasks_marlin_chunks.py; see tasks_sim_full.py for the
# general remarks on the full simulation/reconstruction tasks. The high-level reconstruction
# and analysis follow in tasks_k4run_high_level_reco.py/tasks_k4run_analysis.py.


class K4RunLowLevelRecoIndex(BaseTask):
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

    processes.npy is carried over unchanged from the GeneratorIndex, since cross-section/
    process-level information does not change between the generator and
    simulation stages.
    """

    overview:bool = cast(bool, luigi.BoolParameter(
        description='Whether or not to force showing the overview when the task' +
        ' is already done.',
        default=False))

    def requires(self):
        from .tasks_index import GeneratorIndex

        return {
            'generator_index': GeneratorIndex.req(self),
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
        processes = np.load(inputs['generator_index'][0].path)
        raw_samples = np.load(inputs['generator_index'][1].path)
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


class K4RunLowLevelRecoBaseJob(AbstractK4Run):
    """Base class for k4run low-level reconstruction jobs, running the standard
    reconstruction chain of the detector (e.g. tracking, calorimeter digitisation and
    PandoraPFA) on edm4hep files produced by DDSimFinal. Produces an edm4hep ROOT file
    including a PandoraPFOs collection - analogous to FastSimSGV's output, but from full
    simulation/reconstruction rather than SGV's parametrized fast simulation.

    The steering file is expected to take the arguments --inputFiles, --compactFile,
    --outputFileBase, --lcioOutput and --cmsEnergy (see output_cli), and to write
    <outputFileBase>_REC.edm4hep.root.
    
    This is the case for e.g. ILDConfig's StandardConfig/production/ILDReconstruction.py,
    which requires $ILD_CONFIG_DIR (an ILDConfig checkout) to be set. Parameters are
    injected via task_kwargs['K4RunLowLevelRecoBaseJob'].

    Tasks subclassing this must set `debug`:
    - debug=True (*Runtime jobs): runs on a small subset of K4RunLowLevelRecoIndex's
      samples, capped at debug_n_events_max events each, for a runtime analysis
    - debug=False (*Final jobs): runs over K4RunLowLevelRecoCreateChunks' (grouped)
      chunk plan
    """

    debug = True

    debug_n_files_to_process:int|None = 3
    # cap the runtime-measurement pass to a modest number of events so that timing a
    # single (potentially huge, full-energy) sample doesn't itself take as long as a
    # production job would; unlike DDSimRuntime's debug_n_events_skip, there is no skip
    # here - k4run's event count cap alone is enough for a quick timing sample, and any
    # startup/geometry-loading overhead is instead removed via the usual T0 correction
    # (see K4RunLowLevelRecoCreateChunks.T_STARTUP and get_adjusted_time_per_event)
    debug_n_events_max:int = 50

    def pre_run_command(self, **kwargs):
        self.inject_task_kwargs()

    def inject_task_kwargs(self):
        """Parameter injection from registered configurations, same mechanism as MarlinBaseJob"""
        config = configurations.get(str(self.tag))

        if 'K4RunLowLevelRecoBaseJob' in config.task_kwargs:
            task_kwargs = config.task_kwargs['K4RunLowLevelRecoBaseJob']

            for prop, value in (task_kwargs(self) if isinstance(task_kwargs, Callable) else task_kwargs).items():
                setattr(self, prop, value)

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
            # one or more whole DDSimFinal output files as one concatenated event stream
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

    # the steering file appends _REC.edm4hep.root (and possibly further files, e.g. AIDA
    # or PfoAnalysis ones, which are discarded) to outputFileBase itself
    produced_file = 'out_REC.edm4hep.root'

    # Make sure the chosen CMS energy is implemented by the detector model
    cms_energy:int = 500

    def output_cli(self)->str:
        # --lcioOutput off skips the (unused) additional LCIO-format output of the steering file
        return f'--outputFileBase "$OLDPWD/out" --lcioOutput off --cmsEnergy {self.cms_energy}'

    def workflow_requires(self):
        reqs = {}
        reqs['index_task'] = K4RunLowLevelRecoIndex.req(self)
        # the low-level reconstruction always needs DDSimFinal to have fully completed -
        # not just for K4RunLowLevelRecoIndex's samples.npy, but because that samples.npy
        # references DDSimFinal's own produced files as input
        reqs['full_sim'] = DDSimFinal.req(self)
        if not self.debug:
            reqs['k4run_chunks'] = K4RunLowLevelRecoCreateChunks.req(self)

        return reqs

    def requires(self):
        # branch-level mirror of workflow_requires() so the dynamic
        # workflow_condition evaluates identically whether it is called on the
        # workflow or on a branch task (self.input() otherwise resolves to an
        # empty dict on branches -> all([]) == True -> condition wrongly "met")
        return self.workflow_requires()


class K4RunLowLevelRecoRuntime(K4RunLowLevelRecoBaseJob):
    """Runs the low-level reconstruction chain via k4run on a small subset of
    DDSimFinal's output, for a runtime analysis.
    """
    debug = True


class K4RunLowLevelRecoFinal(K4RunLowLevelRecoBaseJob):
    """Runs the low-level reconstruction chain via k4run for the full production,
    using K4RunLowLevelRecoCreateChunks' chunk plan. Produces one edm4hep ROOT file
    (including a PandoraPFOs collection) per chunk - no other auxiliary files
    are kept as part of this task's output. Requires DDSimFinal.
    """
    debug = False


class K4RunLowLevelRecoCreateChunks(AbstractCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each k4run job, in seconds.', default=3600))

    # k4run/geometry-loading startup overhead, in seconds
    T_STARTUP = 20

    # don't let a downstream CreateChunks task's jobtime leak into the ones it requires
    exclude_params_req_get = {'jobtime'}

    def requires(self):
        return [
            K4RunLowLevelRecoIndex.req(self),
            K4RunLowLevelRecoRuntime.req(self),
            CreateDDSimChunks.req(self)
        ]

    def run(self):
        from .utils.normalization import get_process_normalization, get_sample_chunk_splits, construct_sample_groups, CHUNK_SPLIT_MODES
        from .utils.runtime_analysis import get_runtime_analysis_from_meta, get_adjusted_time_per_event

        inputs = self.input()
        processes = np.load(inputs[0][0].path)
        samples = np.load(inputs[0][1].path)
        sim_chunks = np.load(inputs[2][0].path)

        # groups DDSimFinal's per-source-file chunks back together by originating
        # sample, mirroring how CreateAnalysisChunks groups RecoFinal's chunked output
        # for the Analysis stage (see construct_sample_groups/get_sample_chunk_splits_m2m_grouped)
        sample_groups = construct_sample_groups(sim_chunks, samples)

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
