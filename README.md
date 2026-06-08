# hep-workflows

This repository includes [luigi](https://github.com/spotify/luigi) and [law](https://github.com/riga/law) workflow implementations of common HEP workloads such as event generation and simulation.

## Setup

We assume key4hep is available through cvmfs. Also, we assume `law` is available on the command line and the `tqdm` Python module is installed.

If they are not, you can ensure both conditions by first sourcing the key4hep environment, then using a virtual environment (e.g. `python -m virtualenv testenv && source testenv/bin/activate`) and running

```pip install -r requirements.txt```

When first running workflows, execute `law index --verbose`. Now all workflows tasks are available on the command line through `law run <task>`. Note: The index command must be rerun whenever `law.cfg` is changed or a new task is implemented in a Python file.

## Tasks

