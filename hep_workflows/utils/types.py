from typing import TypedDict, Optional

SGVOptions = dict[str, str|int|float]

class WhizardOption(TypedDict):
    process_name: str
    process_definition: str
    template_dir: str
    sindarin_file: str
    iters_per_polarization:dict[str, int]|None
    nevents: Optional[int]

MarlinBranchValue = tuple[list[str]|str, int, int, int|None, int, str, str|None]
# [0]: input file: str if [6] is None, else must be list[str] input files
# [1]: chunk index of the given input file
# [2]: total number of chunks for the file
# [3]: n_events_skip
# [4]: n_events_max
# [5]: mcp_col_name
# [6]: str output basename or None (if using debug mode or non-grouped submission, i.e. no sub_branch_size column in chunks typed array)

class MarlinSteeringDict(TypedDict):
    executable: str
    input_files: list[str]
    n_events_skip: int|None
    n_events_max: int|None
    mcp_col_name: str
    output_bname: str|None

DDSimBranchValue = tuple[str, int, int, int|None, int, str, str]
# [0]: input LCIO file (generator-level, e.g. from WhizardEventGeneration)
# [1]: chunk index of the given input file
# [2]: total number of chunks for the file
# [3]: n_events_skip (chunk_start), or None
# [4]: n_events_max (chunk_size); -1 means "unset", falling back to AbstractDDSim.n_events_max
# [5]: process
# [6]: proc_pol

K4RunBranchValue = tuple[list[str], int, str, str, str]
# [0]: input edm4hep files (all produced by DDSimFinal); read as one concatenated event stream
# [1]: n_events_max; -1 means "no limit, process all events in the input files"
# [2]: process
# [3]: proc_pol
# [4]: output name (already resolved, so build_command/output() don't need to re-read chunks.npy)