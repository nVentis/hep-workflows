# coding: utf-8

import luigi

from .BaseTask import BaseTask
from ...framework import HTCondorWorkflow


class BaseWorkflowTask(BaseTask, HTCondorWorkflow):
    """Common base for every batch-submitting task in this package.

    Bundles BaseTask (tag handling, local_path/target helpers) with the
    HTCondorWorkflow batch-submission mixin and adds workflow-wide parameters
    that are not specific to any single stage.
    """

    runtime_multiplier = luigi.FloatParameter(
        default=1.0,
        significant=False,
        description='scale the requested runtime of every submitted job by this factor '
                    '(e.g. --runtime-multiplier 2 to re-run a tag whose jobs timed out '
                    'with double the reservation); combines multiplicatively with the '
                    'automatic per-retry escalation and, unlike it, also applies on the '
                    'first attempt. default: 1.0',
    )

    runtime_escalation = luigi.BoolParameter(
        default=False,
        significant=False,
        description='enable automatic runtime escalation for resubmitted jobs: a job '
                    'killed for exceeding its reserved runtime is granted progressively '
                    'more wall time on each retry (see HTCondorWorkflow.job_runtime_seconds). '
                    'disabled by default so retries keep requesting the batch-system '
                    'default runtime; pass --runtime-escalation to opt in.',
    )
