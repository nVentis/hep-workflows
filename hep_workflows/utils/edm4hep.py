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
