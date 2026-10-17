from typing import cast

import luigi

from .framework import configurations
from .tasks_k4run import AbstractK4RunChunkedJob, AbstractK4RunCreateChunks
from .tasks_k4run_high_level_reco import K4RunHighLevelRecoCreateChunks

# Channel-specific analysis via k4run on the output of the high-level reconstruction (see
# tasks_k4run_high_level_reco.py). Used instead of AnalysisRuntime/CreateAnalysisChunks/AnalysisFinal
# (tasks_marlin.py) if AnalysisConfiguration.analysis == 'k4run'. The intended chain is
#
#   ... -> K4RunHighLevelRecoFinal -> AnalysisIndex -> K4RunAnalysisRuntime
#       -> K4RunAnalysisCreateChunks -> K4RunAnalysisFinal
#
# See resources/k4run/analysis_lepton_pairing.py for an example steering file.


class K4RunAnalysisBaseJob(AbstractK4RunChunkedJob):
    """Base class for k4run analysis jobs, running a steering file on the edm4hep files
    produced by K4RunHighLevelRecoFinal (indexed by AnalysisIndex). Steering file, compact
    file and further parameters are injected via task_kwargs['K4RunAnalysisBaseJob'].
    Files the steering file writes in addition to the edm4hep output (e.g. ROOT files
    with ntuples) can be kept via extra_output_files, see AbstractK4Run.

    Tasks subclassing this must set `debug`, see AbstractK4RunChunkedJob.
    """

    task_kwargs_key = 'K4RunAnalysisBaseJob'

    produced_file = 'out_ANA.edm4hep.root'

    # the steering file is self-contained; keep the job's working directory
    run_in_steering_dir = False

    def workflow_requires(self):
        from .tasks_index import AnalysisIndex

        reqs = {}
        reqs['index_task'] = AnalysisIndex.req(self)
        if not self.debug:
            reqs['k4run_chunks'] = K4RunAnalysisCreateChunks.req(self)

        return reqs


class K4RunAnalysisRuntime(K4RunAnalysisBaseJob):
    """Runs the analysis steering file on a small subset of the high-level
    reconstruction output, for a runtime analysis.
    """
    debug = True


class K4RunAnalysisFinal(K4RunAnalysisBaseJob):
    """Runs the analysis steering file for the full analysis, using
    K4RunAnalysisCreateChunks' chunk plan. Produces one edm4hep ROOT file per chunk.
    """
    debug = False


class K4RunAnalysisCreateChunks(AbstractK4RunCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each k4run job, in seconds.', default=1800))

    # k4run/geometry-loading startup overhead, in seconds
    T_STARTUP = 20

    def requires(self):
        from .tasks_index import AnalysisIndex

        return [
            AnalysisIndex.req(self),
            K4RunAnalysisRuntime.req(self),
            K4RunHighLevelRecoCreateChunks.req(self)
        ]
