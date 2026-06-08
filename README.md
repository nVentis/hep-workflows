# hep-workflows

This repository includes [luigi](https://github.com/spotify/luigi) and [law](https://github.com/riga/law) workflow implementations of common HEP workloads such as event generation, simulation and reconstruction.

## Setup

We assume key4hep is available through cvmfs. Also, we assume `law` is available on the command line and the `tqdm` Python module is installed.

If they are not, you can ensure both conditions by first sourcing the key4hep environment (note down the release you use), then using a virtual environment (e.g. `python -m virtualenv testenv && source testenv/bin/activate`) and running

```pip install -r requirements.txt```

When first running workflows, execute `law index --verbose`. Now all workflows tasks are available on the command line through `law run <task>`. Note: The index command must be rerun whenever `law.cfg` is changed or a new task is implemented in a Python file.

For all tasks that run shell scripts (specifically the batch jobs), it is important to get the software environment right. Batch jobs will source the `setup_batch.sh` script before running.

To make sure the software environment is reproducible, we use an `.env` file which should minimally include

    DATA_PATH="/data/dust/user/$(whoami)/zhh"
    SGV_DIR="<PATH_TO_SGV> (if running fast sim is desired)"
    K4H_RELEASE="<YOUR KEY4HEP RELEASE> (not a nightly)"
    ENVIRONMENT_PATH="this_dir/testenv (if you used the above command)"

Output data is stored at `$DATA_PATH`.

An example (usable at DESY) would be:

    DATA_PATH="/data/dust/user/$(whoami)/zhh"
    SGV_DIR="/afs/desy.de/group/flc/pool/bliewert/MarlinWorkdirs/ZHH/dependencies/sgv"
    K4H_RELEASE="2025-01-28"
    ENVIRONMENT_PATH="/afs/desy.de/group/flc/pool/bliewert/MarlinWorkdirs/ZHH/dependencies/hep-workflows/testenv"

## Usage

After setup, you can execute tasks using `law run <TASK_NAME> [--TASK_PARAMETERS] [--branch=<BRANCH_NUMBER>]`. See the [tests](#tests) section for an example.

For certain tasks, you can supply additional parameters through the double "-" notation.

For workflow tasks, you can also specify the option `--branch=<BRANCH_NUMBER>` if you only want to run one out of a range of jobs to be submitted.

## Tasks and Workflows

Tasks are executed on the current node.

Workflows are executed on a cluster (here, so far only HTCondor is supported). They implement a workflow class like `HTCondorWorkflow` or `law.LocalWorkflow`.

Tasks and workflows may depend on each other. If a task/workflow has an `output()` method, it can be used to define _targets_. Only once all targets exist, a task is only considered done. If a task `B` depends on a task `A` which provides targets, `B` can use them as inputs.

### WhizardEventGeneration

This workflow runs event generation using the Whizard version provided by your key4hep version. It sources an `env_script` (defaults to `$ANALYSIS_PATH/setup_batch.sh`), then copies the `TEMPLATE_DIR` directory (defaults to `resources/whizard_template`) to `$DATA_PATH/<task_name>/<tag>/<outputBasename()>` directory.

In this working directory, `SINDARIN_FILE` is copied to `process.sin`. In this file, a few replacements are done and then `whizard process.sin` is called. Finally, we expect the output file at `outputBasename()` and, if it's there, move it to the parent directory to `$DATA_PATH/<task_name>/<tag>/<outputBasename().slcio`.

### FastSimSGV

This workflow runs [SGV](https://gitlab.desy.de/mikael.berggren/sgv) fast simulation on the provided input files and a given steering file. For this to work, the `SGV_DIR` environment variable must exist.

For each input `LCIO` file, exactly one output `LCIO` file is written.

### RawIndex / AnalysisIndex
TODO: Documentation

### MarlinBaseJob
TODO: Documentation

### RecoRuntime / AnalysisRuntime
TODO: Documentation

### RecoFinal / AnalysisFinal
TODO: Documentation

## Tests

`tests/tests_e550_bbbb.py` includes a minimal example to run event generation using Whizard, fast simulation using SGV and an overview of the produced files using the `ProcessIndex` class.

It provides the tasks: `TestGeneratorE550bbbb`, `TestSGVE550bbbb` and `TestIndex550bbbb`

You can run them via `law run TestIndex550bbbb`

## Configurations

Maybe the most useful feature of this repository is that the whole flow from event generation to analysis in Marlin is covered when you use common configuration sets. For this, you need to register an `AnalysisConfiguration` in the `configurations` object from `framework.py`.

An `AnalysisConfiguration` can supply options for event generation or, alternatively, a list of generated event files, parameters for simulation and reconstruction in Marlin. Each configuration has a unique `tag` property, which allows to run tasks one after another using a syntax `law run <TASK_NAME> --tag=<TAG>`. The correct order of tasks is:

1. WhizardEventGeneration
2. FastSimSGV
3. RawIndex
4. RecoRuntime
5. CreateRecoChunks
6. RecoFinal
7. AnalysisIndex
8. AnalysisRuntime
9. CreateAnalysisChunks
10. AnalysisFinal

You can also specify to start with the final task `AnalysisFinal`, `law` will figure out the rest for you and start with the first non-finished task/workflow.

An example is in `tests/tests_e550_hh.py`. (TODO)

## Plugins

In order to extend this code, you can use Python entrypoints, which are loaded in `framework.py`. If you are implementing tasks in a repository `repo-B`, you can use the following structure to use this mechanism

    repo-B/
    ├── pyproject.toml
    └── repo_B/
        ├── __init__.py
        ├── plugin.py
        └── tasks.py

In the `pyproject.toml` file, you can reference a function that registers your tasks under the `hep_workflows.tasks` entrypoint:

    [project]
    name = "repo-b"
    version = "0.1.0"

    [project.entry-points."hep_workflows.tasks"]
    repo_b = "repo_b.plugin:register"

Then, finally, in `repo_b/plugin.py`, you can have

    def register():
        from .tasks import *

assuming you have defined all your tasks at `repo_b/tasks.py`. Then, when `framework.py` looks for registered entrypoints, it will call the `register` function in the external repository and all tasks are loaded.

## More examples

For more examples, see the ILDAnaSoft [ZHH](https://github.com/ILDAnaSoft/ZHH) repository.