import os
import uproot as ur

from .filenames import splitext_mod

def edm4hep_event_count(file: str) -> int:
    """Returns the number of events contained in an edm4hep ROOT file, i.e. the
    number of entries in its 'events' TTree.

    This is the Python-native equivalent of the bin/edm4hep_event_counter shell
    script.

    Args:
        file (str): path to an .edm4hep.root file

    Returns:
        int: number of events in the file
    """

    with ur.open(file) as rf:
        return int(rf['events'].num_entries)


def edm4hep_meta_path(file: str) -> str:
    """Returns the path of the meta.json timing/physics sidecar of a file produced by a task
    running Marlin/k4run/ddsim (see AbstractRecoAna and AbstractDDSim): the output of these tasks is
    a file <name>.<ext> and a directory <name>, which contains the meta.json
    """
    path = f'{splitext_mod(file)[0]}/meta.json'

    if not os.path.isfile(path):
        raise FileNotFoundError(f'No meta.json sidecar found for {file}: {path}')

    return path

def index_edm4hep_files(files: list[str], processes: 'np.ndarray', upstream_samples: 'np.ndarray') -> 'np.ndarray':
    """Builds a samples array (ProcessIndex.dtype_sample) for edm4hep files produced by
    tasks running Marlin/k4run/ddsim. edm4hep files don't carry the physics-process bookkeeping
    (crossSection, processName, ...) Whizard writes into LCIO, so instead:
    - process, proc_pol, the number of events and the sample ID (the law branch number of
      the producing job) are read from the file's .meta.json sidecar
    - cross-sections and polarizations are taken from `processes`, i.e. the processes.npy
      of the index of an earlier stage (see AbstractIndex, key 'upstream_index')
    - run_id is taken from the first sample of the same proc_pol in `upstream_samples`

    Args:
        files (list[str]): .edm4hep.root files to index
        processes (np.ndarray): ProcessIndex.dtype_process-shaped array
        upstream_samples (np.ndarray): ProcessIndex.dtype_sample-shaped array

    Returns:
        np.ndarray: ProcessIndex.dtype_sample-shaped array, sorted by sample ID
    """
    import json
    import numpy as np
    from .ProcessIndex import ProcessIndex

    rows = []
    for position, file in enumerate(files):
        with open(edm4hep_meta_path(file)) as meta_file:
            meta = json.load(meta_file)

        proc_pol = meta['proc_pol']
        process_rows = processes[processes['proc_pol'] == proc_pol]
        upstream_rows = upstream_samples[upstream_samples['proc_pol'] == proc_pol]

        if len(process_rows) != 1 or len(upstream_rows) == 0:
            raise Exception(f'Cannot index <{file}>: proc_pol <{proc_pol}> not found in the upstream index')

        rows.append((
            int(meta.get('branch', position)), int(upstream_rows['run_id'][0]), meta['process'], proc_pol,
            int(meta['nEvtSum']), int(process_rows['pol_e'][0]), int(process_rows['pol_p'][0]), file, 'MCParticles'
        ))

    samples = np.array(rows, dtype=ProcessIndex.dtype_sample)

    if len(np.unique(samples['sid'])) != len(samples):
        raise Exception('Sample IDs (branch numbers in the .meta.json files) are not unique')

    return samples[np.argsort(samples['sid'])]
