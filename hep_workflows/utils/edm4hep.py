import uproot as ur

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
    """Returns the path of the <name>.meta.json timing/physics sidecar that AbstractDDSim
    and AbstractK4Run tasks write next to their <name>.edm4hep.root output."""

    assert file.endswith('.edm4hep.root'), f'Not an .edm4hep.root file: {file}'

    return file[:-len('.edm4hep.root')] + '.meta.json'

def index_edm4hep_files(files: list[str], processes: 'np.ndarray', generator_samples: 'np.ndarray') -> 'np.ndarray':
    """Builds a samples array (ProcessIndex.dtype_sample) for edm4hep files produced by
    AbstractK4Run tasks. edm4hep files don't carry the physics-process bookkeeping
    (crossSection, processName, ...) Whizard writes into LCIO, so instead:
    - process, proc_pol, the number of events and the sample ID (the law branch number of
      the producing job) are read from the file's .meta.json sidecar
    - cross-sections and polarizations are taken from `processes`, i.e. the processes.npy
      of the GeneratorIndex
    - run_id is taken from the first sample of the same proc_pol in `generator_samples`

    Args:
        files (list[str]): .edm4hep.root files to index
        processes (np.ndarray): ProcessIndex.dtype_process-shaped array
        generator_samples (np.ndarray): ProcessIndex.dtype_sample-shaped array

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
        generator_rows = generator_samples[generator_samples['proc_pol'] == proc_pol]

        if len(process_rows) != 1 or len(generator_rows) == 0:
            raise Exception(f'Cannot index <{file}>: proc_pol <{proc_pol}> not found in the GeneratorIndex')

        rows.append((
            int(meta.get('branch', position)), int(generator_rows['run_id'][0]), meta['process'], proc_pol,
            int(meta['nEvtSum']), int(process_rows['pol_e'][0]), int(process_rows['pol_p'][0]), file, 'MCParticles'
        ))

    samples = np.array(rows, dtype=ProcessIndex.dtype_sample)

    if len(np.unique(samples['sid'])) != len(samples):
        raise Exception('Sample IDs (branch numbers in the .meta.json files) are not unique')

    return samples[np.argsort(samples['sid'])]
