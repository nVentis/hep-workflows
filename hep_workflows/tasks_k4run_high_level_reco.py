from typing import cast

import luigi

from .framework import configurations
from .tasks_k4run import AbstractK4RunChunkedJob, AbstractK4RunCreateChunks
from .tasks_k4run_low_level_reco import K4RunLowLevelRecoCreateChunks

# High-level reconstruction (e.g. jet clustering, isolated lepton/photon identification) via k4run
# on the output of the low-level reconstruction (see tasks_k4run_low_level_reco.py). Used instead of
# RecoRuntime/CreateRecoChunks/RecoFinal (tasks_marlin.py) if AnalysisConfiguration.analysis == 'k4run'.
# The intended chain is
#
#   ... -> K4RunLowLevelRecoFinal -> RawIndex -> K4RunHighLevelRecoRuntime
#       -> K4RunHighLevelRecoCreateChunks -> K4RunHighLevelRecoFinal
#
# where RawIndex indexes AnalysisConfiguration.high_level_reco_input_files, which defaults to the output
# of K4RunLowLevelRecoFinal for analysis == 'k4run'. See resources/k4run/high_level_reco.py for an example
# steering file.


class K4RunHighLevelRecoBaseJob(AbstractK4RunChunkedJob):
    """Base class for k4run high-level reconstruction jobs, running a steering
    file on the edm4hep files indexed by RawIndex. Steering file, compact file and
    further parameters are injected via task_kwargs['K4RunHighLevelRecoBaseJob'].

    Tasks subclassing this must set `debug`, see AbstractK4RunChunkedJob.
    """

    task_kwargs_key = 'K4RunHighLevelRecoBaseJob'

    produced_file = 'out_HLR.edm4hep.root'

    # the steering file is self-contained; keep the job's working directory
    run_in_steering_dir = False

    def workflow_requires(self):
        from .tasks_index import RawIndex

        reqs = {}
        reqs['index_task'] = RawIndex.req(self)
        if not self.debug:
            reqs['k4run_chunks'] = K4RunHighLevelRecoCreateChunks.req(self)

        # inject dynamic workflow requirements from the registered configuration
        configurations.get(str(self.tag)).task_requires(self, reqs)

        return reqs


class K4RunHighLevelRecoRuntime(K4RunHighLevelRecoBaseJob):
    """Runs the high-level reconstruction steering file on a small subset of
    the low-level reconstruction output, for a runtime analysis.
    """
    debug = True


class K4RunHighLevelRecoFinal(K4RunHighLevelRecoBaseJob):
    """Runs the high-level reconstruction steering file for the full production,
    using K4RunHighLevelRecoCreateChunks' chunk plan. Produces one edm4hep ROOT file
    per chunk.
    """
    debug = False


class K4RunHighLevelRecoCreateChunks(AbstractK4RunCreateChunks):
    jobtime:int = cast(int, luigi.IntParameter(description='Maximum runtime of each k4run job, in seconds.', default=3600))

    # k4run/geometry-loading startup overhead, in seconds
    T_STARTUP = 20

    def requires(self):
        from .tasks_index import RawIndex

        return [
            RawIndex.req(self),
            K4RunHighLevelRecoRuntime.req(self),
            K4RunLowLevelRecoCreateChunks.req(self)
        ]
