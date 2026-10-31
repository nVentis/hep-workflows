# hep-workflows

This repository includes [luigi](https://github.com/spotify/luigi) and [law](https://github.com/riga/law) workflow implementations of common HEP workloads such as event generation, simulation and reconstruction.

## Setup

We assume key4hep is available through cvmfs. Also, we assume `law` is available on the command line and the `tqdm` Python module is installed.

If they are not, you can ensure both conditions by first sourcing the key4hep environment (note down the release you use), then using a virtual environment (e.g. `python -m virtualenv testenv && source testenv/bin/activate`) and running

    pip install -e 
    
to install this package and all dependencies. 

When first running workflows, execute `law index --verbose`. Now all workflows tasks are available on the command line through `law run <task>`. Note: The index command must be rerun whenever `law.cfg` is changed or a new task is implemented in a Python file.

For all tasks that run shell scripts (specifically the batch jobs), it is important to get the software environment right. Batch jobs will source the `setup.sh` script before running.

To make sure the software environment is reproducible, we use an `.env` file which should minimally include

    DATA_PATH="/data/dust/user/$(whoami)/zhh"
    SGV_DIR="<PATH_TO_SGV> (if running fast sim is desired)"
    K4H_RELEASE or K4H_NIGHTLY="<RELEASE or WEEKDAY or latest>"
    PYTHON_ENVIRONMENT_PATH="this_dir/testenv (if you used the above command)"

Output data is stored at `$DATA_PATH`.

An example (usable at DESY) would be:

    DATA_PATH="/data/dust/user/$(whoami)/zhh"
    SGV_DIR="/afs/desy.de/group/flc/pool/$(whoami)/MarlinWorkdirs/ZHH/dependencies/sgv"
    K4H_RELEASE="2025-01-28"
    PYTHON_ENVIRONMENT_PATH="/afs/desy.de/group/flc/pool/$(whoami)/MarlinWorkdirs/ZHH/dependencies/hep-workflows/testenv"

Instead of `K4H_RELEASE`, you can set `K4H_NIGHTLY` (takes priority over `K4H_RELEASE`) to source a key4hep nightly build instead of a dated release - required for
`DDSim` and `LowLevelReco` tasks (see below), since ILD@FCC-ee support isn't available on a release
yet. On AlmaLinux 9, this is the LCG `devkey-head` view: the value is the weekday of the nightly (`Mon`, `Tue`, ..., `Sat`; there are no Sunday builds) or `latest`:

    K4H_NIGHTLY="latest"

`setup.sh` also adds the library directories of the view to `LIBRARY_PATH`, which Whizard needs to link its process libraries.

## Usage

After setup, you can execute tasks using `law run <TASK_NAME> [--TASK_PARAMETERS] [--branch=<BRANCH_NUMBER>]`. See the [tests](#tests) section for an example.

For certain tasks, you can supply additional parameters through the double "-" notation.

For workflow tasks, you can also specify the option `--branch=<BRANCH_NUMBER>` if you only want to run one out of a range of jobs to be submitted.

## Tasks and Workflows

Tasks are executed on the current node.

Workflows are executed on a cluster (here, so far only HTCondor is supported). They implement a workflow class like `HTCondorWorkflow` or `law.LocalWorkflow`.

Tasks and workflows may depend on each other. If a task/workflow has an `output()` method, it can be used to define _targets_. Only once all targets exist, a task is only considered done. If a task `B` depends on a task `A` which provides targets, `B` can use them as inputs.

### Runtime escalation / multiplier

All workflow tasks (subclasses of `BaseWorkflowTask`) accept two parameters controlling the wall time requested for their HTCondor jobs:

- `--runtime-escalation`: opt-in flag (default: off). When set, a job killed for exceeding its reserved runtime is granted progressively more wall time on each retry, capped after a few attempts. Disabled by default, so retries keep requesting the batch-system default runtime.
- `--runtime-multiplier=<factor>`: scales the requested runtime of every submitted job by `<factor>` (default: `1.0`), applying from the very first attempt regardless of `--runtime-escalation`. Useful to re-run a tag whose jobs previously timed out with more head room, e.g. `--runtime-multiplier=2`.

### WhizardEventGeneration

This workflow runs event generation using the Whizard version provided by your key4hep version. It sources an `env_script` (defaults to `$ANALYSIS_PATH/setup.sh`), then copies the `TEMPLATE_DIR` directory (defaults to `resources/whizard_template`) to `$DATA_PATH/<task_name>/<tag>/<outputBasename()>` directory.

In this working directory, `SINDARIN_FILE` is copied to `process.sin`. In this file, a few replacements are done and then `whizard process.sin` is called. Finally, we expect the output file at `outputBasename()` and, if it's there, move it to the parent directory to `$DATA_PATH/<task_name>/<tag>/<outputBasename().slcio`.

### FastSimSGV

This workflow runs [SGV](https://gitlab.desy.de/mikael.berggren/sgv) fast simulation on the provided input files and a given steering file. For this to work, the `SGV_DIR` environment variable must exist.

For each input `LCIO` file, exactly one output `LCIO` file is written.

### GeneratorIndex / RawIndex / AnalysisIndex
TODO: Documentation

`RawIndex` indexes the input of the high-level reconstruction, i.e. the files given by `AnalysisConfiguration.high_level_reco_input_files`; for legacy reasons, this defaults to `slcio_files` (only meaningful for fast-sim workflows, where it defaults to the output of `FastSimSGV`), and all internal code uses `high_level_reco_input_files`. `GeneratorIndex` is the equivalent for the generator-level LCIO files `AnalysisConfiguration.generator_files` which are the input to the simulation, i.e. a requirement of both `FastSimSGV` (if the generator files are known, i.e. `whizard_options` are given) and `DDSim*`. `generator_files` defaults to the output of `WhizardEventGeneration` if `whizard_options` are given; otherwise (full-sim only) it must be set. When the files are edm4hep files (`low_level_reco`/`high_level_reco = RECO_ANA_RUNMODES.K4RUN`, see [Stages](#stages-low_level_reco-high_level_reco-analysis)), `RawIndex` and `AnalysisIndex` index them instead of LCIO files: since these do not carry the physics process bookkeeping Whizard writes into LCIO, process/polarization/event numbers are read from the `meta.json` sidecar each job writes, and cross-sections from the index of the previous stage (`GeneratorIndex` for `RawIndex`, `RawIndex` for `AnalysisIndex`; required as `upstream_index`).

### RecoAnaBaseJob
TODO: Documentation

### RecoRuntime / AnalysisRuntime
TODO: Documentation

### RecoFinal / AnalysisFinal
TODO: Documentation

### Full simulation (ddsim) and k4run based reconstruction and analysis

These run full simulation (via `ddsim`), reconstruction (via `k4run`) and analysis for the [ILD@FCC-ee](https://github.com/HEP-FCC/FCC-config/blob/main/FCCee/FullSim/ILD_FCCee/README.md) detector models (`ILD_FCCee_v01`/`ILD_FCCee_v02`) and the ILD@ILC models, as an alternative to `FastSimSGV` and Marlin. All output a single edm4hep ROOT file per chunk - no AIDA/PfoAnalysis/log files are kept - and the output of `K4RunLowLevelRecoFinal` includes a `PandoraPFOs` collection, making it usable wherever `FastSimSGV`'s output would be.

Full ILD@FCC-ee support currently only exists on **key4hep nightlies**, not a dated release - set `$K4H_NIGHTLY` (see [Setup](#setup)) so setup.sh/bootstrap.sh sources a nightly before these tasks run. They deliberately don't (re-)source a nightly stack themselves: key4hep's nightly setup.sh refuses to run on top of an already-sourced stack, which is always the case by the time a job's command runs.

Like `RecoRuntime`/`RecoFinal`, each stage is really a Runtime/CreateChunks/Final triple performing a runtime analysis, then a chunking, then the full production run:

- `DDSimRuntime` / `CreateDDSimChunks` / `DDSimFinal` (`tasks_sim_full.py`) - reads `GeneratorIndex`'s generator-level LCIO samples (ddsim reads LCIO input directly, no conversion needed) and writes edm4hep files with simulated hits (one file and one directory per sample chunk, via a `ONE_TO_MANY` split, same as `CreateRecoChunks`).
- `LowLevelRecoIndex` / `LowLevelRecoRuntime` / `CreateLowLevelRecoChunks` / `LowLevelRecoFinal` (`tasks_low_level_reco.py`) - the low level reconstruction after ddsim. The index re-indexes `DDSimFinal`'s actual output (using `edm4hep_event_count()`, since these are edm4hep, not LCIO, files) into the same samples.npy/processes.npy shape `AbstractIndex` produces, analogous to how `AnalysisIndex` re-indexes `RecoFinal`'s output. The reconstruction (`LowLevelRecoAbstract`, a `RecoAnaBaseJob`) runs the detector's reconstruction chain (tracking, calo digitisation, PandoraPFA), grouping `DDSimFinal`'s per-source-file chunks back together (a `MANY_TO_MANY` split, same as `CreateAnalysisChunks`).
- `RecoRuntime` / `CreateRecoChunks` / `RecoFinal` and `AnalysisRuntime` / `CreateAnalysisChunks` / `AnalysisFinal` (`tasks_reco_ana.py`, `tasks_chunks.py`) - the high level reconstruction (e.g. jet clustering, isolated lepton/photon identification) and the channel-specific analysis. They are used for both Marlin and k4run: with `high_level_reco`/`analysis = RECO_ANA_RUNMODES.K4RUN`, a Gaudi steering file is run via `k4run` instead of a Marlin steering file via `Marlin` (see `AbstractRecoAna.build_command`). For full simulation, `RawIndex` indexes the output of `LowLevelRecoFinal`, i.e. the input of `RecoRuntime`/`RecoFinal`. Chunking works exactly as with Marlin (events are skipped via `LcioEvent.skipNEvents` for LCIO and `IOSvc.FirstEventEntry` for edm4hep input).

All these tasks derive from `AbstractRecoAna` (`tasks_reco_ana.py`): depending on the `RECO_ANA_RUNMODES` of the stage, it runs `Marlin` or `k4run <steering_file>` with the input files, the compact file and an output file name; what happens is up to the steering file. What the tasks do is independent of the implementation. Every job has a directory (everything the steering file writes, and a `meta.json` sidecar with timing, number of events and process) and a file (`output_file`, stored in the branch values; set it via `task_kwargs`) as output, as do the `DDSim` jobs. Steering files with a non-standard command line can have their command built differently by overwriting `build_run_command` via `task_kwargs` (a function receiving the task and the steering parameters, which may call `AbstractRecoAna.build_run_command`), as done by `LowLevelRecoAbstract` for ILDConfig's `ILDReconstruction.py`.

For a config to use this path instead of `FastSimSGV`, set `simulation = EVENT_SIM_ENUM.FULL_DDSIM` on its `AnalysisConfiguration` (see `framework.py`); `slcio_files` is not used for full-sim workflows; the input of ddsim is given by `generator_files`. Marlin cannot read the edm4hep output of ddsim/k4run, see [Stages](#stages-low_level_reco-high_level_reco-analysis) for how to select k4run for the stages after the simulation.

#### Stages: `low_level_reco`, `high_level_reco`, `analysis`

Which framework runs the stages after the simulation is selected per stage by these `AnalysisConfiguration` options (values of `RECO_ANA_RUNMODES`), and the required task dependencies are injected automatically:

| option | values | default |
|---|---|---|
| `low_level_reco` (tracking, calorimeter digitisation, PandoraPFA) | `K4RUN`, or `None` to skip it | `K4RUN` for `FULL_DDSIM`; always `None` (forced) for `FAST_SGV`, whose output is already reconstructed |
| `high_level_reco` (`RecoRuntime`/`RecoFinal`) | `MARLIN`, `K4RUN` | `MARLIN` |
| `analysis` (`AnalysisRuntime`/`AnalysisFinal`) | `MARLIN`, `K4RUN` | `MARLIN` |

Since Marlin cannot read edm4hep, once a stage runs k4run, all following stages must, too (checked when the configuration is created). Gaudi can run on fast simulation samples: for `FAST_SGV`, set `high_level_reco` and/or `analysis` to `K4RUN`; k4run then reads the LCIO output of SGV. Examples: `hep_workflows/configs/test_e250_zh_full_k4run.py` (full simulation) and `test_e250_zh_fast_k4run.py` (fast simulation). There is no full-simulation configuration with a Marlin based high-level reconstruction; for fast simulation, see `test_e250_zh_fast_marlin.py`.

`steering_file`/`compact_file` are obligatory parameters (no built-in default) on both `AbstractDDSim` and the reconstruction/analysis tasks - set them and other options via `task_kwargs['DDSimBaseJob']`/`task_kwargs['LowLevelRecoAbstract']`/..., same mechanism as `task_kwargs['RecoAnaBaseJob']`. `task_kwargs` entries can be given for any class in the inheritance chain, e.g. `'RecoAnaBaseJob'` (all), `'RecoAbstract'` (`RecoRuntime`/`RecoFinal`), `'AnalysisAbstract'` or `'LowLevelRecoAbstract'`. `ddsim_arguments` (same task_kwargs keys) passes extra CLI arguments to `ddsim`. For the reconstruction/analysis tasks, `constants` and `globals` (the `AnalysisConfiguration` options and task attributes, formerly `marlin_constants`/`marlin_globals`) are passed as `--constant.K=V`/`--global.K=V` to Marlin and as `--K V` to k4run. No such parameters (e.g. `ILDConfigDir` for Marlin, `cmsEnergy` for ILDReconstruction.py) are hard-coded: define them in the configuration.

The k4run low level reconstruction runs [ILDConfig](https://github.com/iLCSoft/ILDConfig)'s own `StandardConfig/production/ILDReconstruction.py` directly (via `LowLevelRecoAbstract`'s `steering_file`; set `constants = { 'lcioOutput': 'off', 'cmsEnergy': <energy> }`) - it requires `$ILD_CONFIG_DIR` (an `ILDConfig` checkout) to be set, for the `Calibration`/`Config`/`Tracking`/`CaloDigi`/`ParticleFlow`/`HighLevelReco` files it imports from there.

For the high level reconstruction and the analysis, `resources/k4run` has example steering files. They are called as `k4run <steering_file> --inputFiles <files> --compactFile <file> --outputFile <file> -n <n> [--IOSvc.FirstEventEntry=<n>]` and must write the file given by `--outputFile`. Everything else they write into the working directory ends up in the output directory of the task, next to a `meta.json` sidecar (timing, number of events, process; written for both Marlin and k4run, and replacing the `FinalStateMeta.json` of the ZHH repository, which is still read for already existing directories):

- `high_level_reco.py` runs FastJet, isolated lepton and isolated photon identification (the lepton MVA weights are detector specific: pass `isoElectronWeights`/`isoMuonWeights` via `constants`; by default, the ILD ones from `$ILD_CONFIG_DIR` are used) (adapted from [HInv_ExScalar](https://github.com/ILDAnaSoft/HInv_ExScalar/blob/main/scripts/steering_example.py)).
- `analysis_lepton_pairing.py` only runs the `LeptonPairing` processor on the output of the former. This processor is part of the [ZHH](https://github.com/ILDAnaSoft/ZHH) repository and not of the key4hep stack: it has to be compiled against the key4hep stack in use, and the library is attached via `constants = { 'marlinDll': '<path to library>' }`. The ROOT file with the TTree it fills ends up in the output directory of the task.

An example for all of this is `hep_workflows/configs/test_e250_zh_full_k4run.py`.

**Known upstream issue** (as of the 2026-08-12 nightly): `MyConformalTracking` (from `Tracking/TrackingReco_FCCeeMDI.py`) throws a `map::at` exception while processing events, for both `ILD_FCCee_v01` and `ILD_FCCee_v02`, reproduced with several different `ddsim` particle-gun inputs. This looks like an `ILDConfig`/`k4geo` compatibility gap rather than anything fixable from this repository; ddsim itself (`DDSimFinal`) is unaffected and was verified end-to-end against real `ILD_FCCee_v01`/`v02` geometry.

## Tests

### Test configurations

`hep_workflows/configs` contains small `AnalysisConfiguration`s (e+e- -> mu+mu- h at 250 GeV, two polarizations, 100 events each) that run the chain from `WhizardEventGeneration` to `RecoFinal` (the analysis stage is not covered). Together, they cover the combinations of simulation and framework per stage:

| module | simulation | low-level reco | high-level reco | stack |
|---|---|---|---|---|
| `test_e250_zh_fast_marlin` | SGV | - | Marlin (`resources/marlin/high_level_reco.xml`) | release or nightly |
| `test_e250_zh_fast_k4run` | SGV | - | k4run | nightly |
| `test_e250_zh_full_k4run` | ddsim | k4run | k4run | nightly |

Each configuration installs its dependencies beyond CVMFS in `setup()` (see `configs/provisioning.py`) if `$SGV_DIR`/`$ILD_CONFIG_DIR` do not exist, to `$PROVISION_DIR` (default: `$HOME`). Note that SGV is compiled against the key4hep stack in use: it has to be reinstalled if the stack changes. The Python environment (`PYTHON_ENVIRONMENT_PATH`) is tied to the stack as well.

Run them with an explicit `--module` (law only imports the module defining the requested task). `HEP_WORKFLOWS_DEFAULT_WORKFLOW=local` runs all workflows on the current node instead of HTCondor (the default workflow of all tasks):

    export HEP_WORKFLOWS_DEFAULT_WORKFLOW=local
    law run RecoFinal --tag=250-e2e2h-ild-fast-marlin --module hep_workflows.configs.test_e250_zh_fast_marlin --local-scheduler

`hep_workflows/configs/test_e550_bbbb.py` additionally includes a minimal example to run event generation using Whizard, fast simulation using SGV and an overview of the produced files using the `ProcessIndex` class: `law run TestIndex550bbbb`.

### pytest

    pip install -e ".[test]"
    pytest                      # unit tests; need no software stack
    pytest -m integration       # integration tests

The unit tests cover `utils/filenames.py`, `utils/normalization.py` and the consistency of the configurations and `law.cfg` (`test_configs.py`).

The integration tests (`tests/test_integration.py`) run `law` in a subprocess after sourcing `setup.sh`, i.e. in the same software environment as the batch jobs (key4hep from CVMFS and the Python environment), see `tests/conftest.py`. They check the dependency tree of each configuration and run the chain up to `RecoFinal`, checking that all outputs contain events. The environment is taken from `$HEP_WORKFLOWS_TEST_ENV` (an `.env` file), else `$DOT_ENVIRONMENT_FILE`, else `hep_workflows/.env`, and from the environment variables of the calling process (e.g. in CI); `DATA_PATH` is always replaced by a temporary directory. Tests of the configurations requiring a nightly are skipped unless `K4H_NIGHTLY` is set.

### Continuous integration

`.github/workflows/ci.yml` builds the `Dockerfile` on every push to `main`, pull request and manual run, pushes the image to `ghcr.io/<owner>/<repo>` (tagged with the branch/PR and commit), and runs the tests in parallel jobs in exactly that image (referenced by digest): the unit tests, and one integration test job per test configuration (`fast-marlin`, `fast-k4run`, `full-k4run`).

The image contains the repository, the `law` index (`law index`; `law run` does not find any task without it), the Python environment and SGV, which are tied to the key4hep stack. It also needs `libtirpc-devel`, which Whizard links its process libraries against. ILDConfig (large, independent of the stack) is not part of it: the configurations that need it clone it when the tests run. It is built with the latest key4hep nightly (`K4H_NIGHTLY=latest` is resolved to the weekday of the LCG `devkey-head` view and pinned in `hep_workflows/.env`, so that the tests use the stack the image was built with). CVMFS is mounted by `/mount.sh` (a step of the jobs, and a privileged `RUN` for the build, which needs `docker buildx build --allow security.insecure`). The build cache is deliberately not used: it cannot know about changes of the nightly. Pull requests from forks cannot push to the registry and are not tested.

To run the tests in the image locally:

    docker buildx build --allow security.insecure -t hep-workflows .
    docker run --privileged -it hep-workflows
    source hep_workflows/setup.sh && pytest -m "integration" -k fast-marlin

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

For configurations with `simulation = EVENT_SIM_ENUM.FULL_DDSIM` (see [Full simulation](#full-simulation-ddsim-and-k4run-based-reconstruction-and-analysis)), steps 2-10 above are replaced by:

2. GeneratorIndex
3. DDSimRuntime
4. CreateDDSimChunks
5. DDSimFinal
6. LowLevelRecoIndex
7. LowLevelRecoRuntime
8. CreateLowLevelRecoChunks
9. LowLevelRecoFinal

and the following steps are appended (the same tasks as for fast simulation; with `high_level_reco`/`analysis = RECO_ANA_RUNMODES.K4RUN` they run Gaudi steering files via k4run instead of Marlin):

10. RawIndex
11. RecoRuntime
12. CreateRecoChunks
13. RecoFinal
14. AnalysisIndex
15. AnalysisRuntime
16. CreateAnalysisChunks
17. AnalysisFinal

Examples are in `hep_workflows/configs`.

## Plugins

In order to extend this code, you can use Python entrypoints, which are loaded in `framework.py` when executing tasks using `law`. If you are implementing tasks in a repository `repo-B`, you can use the following structure to use this mechanism

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

Note: Entrypoints only work when the package in `repo-b` was installed correctly, e.g. using `pip install -e .`. Including the directory in PYTHONPATH is _not_ enough.

## More examples

For more examples, see the ILDAnaSoft [ZHH](https://github.com/ILDAnaSoft/ZHH) repository.