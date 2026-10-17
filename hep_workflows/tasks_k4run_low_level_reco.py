from typing import cast

import luigi
import numpy as np

from .utils import BaseTask
from .tasks_sim_full import DDSimFinal, CreateDDSimChunks
from .tasks_k4run import AbstractK4RunChunkedJob, AbstractK4RunCreateChunks

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


class K4RunLowLevelRecoBaseJob(AbstractK4RunChunkedJob):
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

    Tasks subclassing this must set `debug`, see AbstractK4RunChunkedJob.
    """

    task_kwargs_key = 'K4RunLowLevelRecoBaseJob'

    # the steering file appends _REC.edm4hep.root (and possibly further files, e.g. AIDA
    # or PfoAnalysis ones, which are discarded) to outputFileBase itself
    produced_file = 'out_REC.edm4hep.root'

    # Make sure the chosen CMS energy is implemented by the detector model
    cms_energy:int = 500

    def output_cli(self)->str:
        # --lcioOutput off skips the (unused) additional LCIO-format output of the steering file
        return f'--outputFileBase "{self.job_dir_ref()}/out" --lcioOutput off --cmsEnergy {self.cms_energy}'

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


class K4RunLowLevelRecoCreateChunks(AbstractK4RunCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each k4run job, in seconds.', default=3600))

    # k4run/geometry-loading startup overhead, in seconds
    T_STARTUP = 20

    def requires(self):
        return [
            K4RunLowLevelRecoIndex.req(self),
            K4RunLowLevelRecoRuntime.req(self),
            CreateDDSimChunks.req(self)
        ]

    def sample_groups(self, upstream_chunks:np.ndarray, samples:np.ndarray):
        from .utils.normalization import construct_sample_groups

        # groups DDSimFinal's per-source-file chunks back together by originating
        # sample, mirroring how CreateAnalysisChunks groups RecoFinal's chunked output
        # for the Analysis stage (see construct_sample_groups/get_sample_chunk_splits_m2m_grouped)
        return construct_sample_groups(upstream_chunks, samples)
