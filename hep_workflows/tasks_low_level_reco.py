import os.path as osp
from typing import cast

import luigi
import numpy as np

from .utils import BaseTask
from .tasks_reco_ana import RecoAnaBaseJob
from .tasks_sim_full import DDSimFinal

# Low-level reconstruction (e.g. tracking, calo digitisation, PandoraPFA) of the full simulation
# output (DDSimFinal). The intended production chain is
#
#   ... -> DDSimRuntime
#       -> CreateDDSimChunks
#       -> DDSimFinal
#       -> LowLevelRecoIndex
#       -> LowLevelRecoRuntime
#       -> CreateLowLevelRecoChunks
#       -> LowLevelRecoFinal
#
# mirroring RecoRuntime/CreateRecoChunks/RecoFinal and AnalysisRuntime/CreateAnalysisChunks/
# AnalysisFinal in tasks_reco_ana.py/tasks_chunks.py: the tasks are RecoAnaBaseJob tasks running k4run
# (the only supported implementation of AnalysisConfiguration.low_level_reco).


class LowLevelRecoIndex(BaseTask):
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
        from .tasks_chunks import CreateDDSimChunks

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
            location = str(sim_collection[branch][1].path)
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


class LowLevelRecoAbstract(RecoAnaBaseJob):
    """Base class for the low-level reconstruction of the output of DDSimFinal, which has to
    produce an edm4hep file including a PandoraPFOs collection - analogous to FastSimSGV's output, but
    from full simulation rather than SGV's parametrized fast simulation.

    The steering file, e.g. ILDConfig's StandardConfig/production/ILDReconstruction.py (requires
    $ILD_CONFIG_DIR, an ILDConfig checkout), as well as the compact file and other options (constants, for
    example cmsEnergy) are injected via task_kwargs, e.g. under 'LowLevelRecoAbstract'.

    Unlike what AbstractRecoAna.build_run_command assumes, such steering files
    - take --outputFileBase instead of --outputFile and append _REC.edm4hep.root (and, depending
      on the steering file, further files, which are kept in the output directory), i.e. output_file must end with it
    - are run from the directory of the steering file (relative imports)
    Steering files following the standard usage may overwrite build_run_command again via task_kwargs.

    Tasks subclassing this must set `debug`:
    - debug=True (LowLevelRecoRuntime): runs on a small subset of LowLevelRecoIndex's
      samples, capped at n_events_max events each, for a runtime analysis
    - debug=False (LowLevelRecoFinal): runs over CreateLowLevelRecoChunks' (grouped) chunk plan
    """
    stage = 'low_level_reco'

    output_file = 'out_REC.edm4hep.root'

    # the steering file does not know the argument
    pass_mcp_col_name = False

    def build_run_command(self, steering):
        output_file = steering['output_file']
        assert output_file.endswith('_REC.edm4hep.root'), f'output_file must end with _REC.edm4hep.root, got <{output_file}>'

        steering_file = osp.expandvars(self.steering_file)

        cmd = super().build_run_command(steering)
        cmd = cmd.replace(f'k4run "{self.steering_file}"', f'k4run "{osp.basename(steering_file)}"')
        cmd = cmd.replace(f'--outputFile "{output_file}"', f'--outputFileBase "$OLDPWD/{output_file[:-len("_REC.edm4hep.root")]}"')

        # $OLDPWD is the working directory of the job
        return f'( cd "{osp.dirname(steering_file)}" && {cmd} )'

    def workflow_requires(self):
        from .tasks_chunks import CreateLowLevelRecoChunks

        reqs = {}
        reqs['index_task'] = LowLevelRecoIndex.req(self)
        # the low-level reconstruction always needs DDSimFinal to have fully completed -
        # not just for LowLevelRecoIndex's samples.npy, but because that samples.npy
        # references DDSimFinal's own produced files as input
        reqs['full_sim'] = DDSimFinal.req(self)
        if not self.debug:
            reqs['chunks'] = CreateLowLevelRecoChunks.req(self)

        return reqs

    def requires(self):
        # branch-level mirror of workflow_requires(), see RecoAbstract.requires()
        return self.workflow_requires()


class LowLevelRecoRuntime(LowLevelRecoAbstract):
    """Runs the low-level reconstruction on a small subset of DDSimFinal's output, for a runtime analysis.
    """
    debug = True

    # cap the runtime-measurement pass to a modest number of events so that timing a
    # single (potentially huge, full-energy) sample doesn't itself take as long as a
    # production job would; any startup/geometry-loading overhead is removed via the
    # usual T0 correction (see CreateLowLevelRecoChunks.T_STARTUP and get_adjusted_time_per_event)
    n_events_max = 50


class LowLevelRecoFinal(LowLevelRecoAbstract):
    """Runs the low-level reconstruction for the full production, using CreateLowLevelRecoChunks'
    chunk plan. Requires DDSimFinal.
    """
    debug = False
