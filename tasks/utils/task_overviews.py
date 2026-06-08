import numpy as np
from .tasks.BaseTask import BaseTask

def index_overview(samples:np.ndarray,
                   processes:np.ndarray,
                   task_instance:BaseTask|None=None)->str:
    """Creates a text overview for an AbstractIndex task

    Args:
        samples (np.ndarray): _description_
        processes (np.ndarray): _description_
        task_instance (BaseTask | None, optional): An AbstractIndex task. Defaults to None.

    Returns:
        str: _description_
    """
    
    unique_proc_pol = list(processes['proc_pol'])    
    unique_proc_pol.sort()
    
    task_name = '' if task_instance is None else task_instance.__class__.__name__
    samples_file = '<unknown path>' if task_instance is None else str(task_instance.output()[3].path)
    processes_file = '<unknown path>' if task_instance is None else str(task_instance.output()[2].path)    
    
    text = f'''++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
{task_name} Overview: Found {len(processes)} in {len(samples)} sample files!

1. SAMPLES (see {samples_file})

Run ID   | Process      | Polarization |  NEvents  | Location
----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
'''

    for proc_pol in unique_proc_pol:
        process, polarization = proc_pol[:-3], proc_pol[-2:]
        
        for file in samples[samples['proc_pol'] == proc_pol]:
            text += f"{file['run_id']:>11} | "
            text += f"{process:>12} | "
            text += f"{polarization:>12} | "
            text += f"{file['n_events']:>9,} | "            
            text += f"{file['location']}\n"
    
    text += f'''
2. PROCESSES (see {processes_file})

Process      | Polarization | Cross section [fb] | CS. MC error [fb] | NSamples |  NEvents
----------------------------------------------------------------------------------------------
'''

    for proc_pol in unique_proc_pol:
        process, polarization = proc_pol[:-3], proc_pol[-2:]
        p = processes[processes['proc_pol'] == proc_pol]
        assert(len(p) == 1)
        p = p[0]
        
        text += f"{process:>12} | "
        text += f"{polarization:>12} | "
        text += f"{p['cross_sec']:18.4} | "
        text += f"{p['cross_sec_err']:18.4} | "
        text += f"{len(samples[samples['proc_pol'] == proc_pol]):>8,} | "
        text += f"{samples[samples['proc_pol'] == proc_pol]['n_events'].sum():>12,} \n"
        
    return text

def chunk_overview(chunks:np.ndarray,
                   time_per_event:np.ndarray,
                   process_normalization:np.ndarray,
                   task_instance:BaseTask|None=None)->str:
    """Creates a text overview for an AbstractCreateChunks

    Args:
        chunks (np.ndarray): _description_
        time_per_event (np.ndarray): _description_
        process_normalization (np.ndarray): _description_
        task_instance (BaseTask | None, optional): _description_. Defaults to None.

    Returns:
        str: _description_
    """
    
    unique_proc_pol = list(np.unique(chunks['proc_pol']))        
    unique_proc_pol.sort(key=lambda proc_pol: -len(chunks['proc_pol'] == proc_pol))
    
    task_name = '' if task_instance is None else task_instance.__class__.__name__
    chunk_file_path = '<unknown path>' if task_instance is None else str(task_instance.output()[4].path)
    
    is_m2m = 'sub_branch_size' in chunks.dtype.names
    is_grouped_m2m = 'src_bname' in chunks.dtype.names
    size_prop_name = 'chunk_size' if not is_m2m else 'sub_branch_size'
    n_branches_tot = len(chunks) if not is_m2m else len(np.unique(chunks['branch']))
    chunk_mode = 'ONE-TO-MANY' if not is_m2m else ('MANY-TO-MANY (GROUPED)' if is_grouped_m2m else 'MANY-TO-MANY (NON-GROUPED)')
    
    text = f'''+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
{task_name} Overview: Divided submission into {n_branches_tot} chunks with {int(np.sum(chunks[size_prop_name])):,} events

    Chunk mode : <{chunk_mode}>
    Chunk list : <{chunk_file_path}>

 NChunks(branches) | Process      | Polarization | t/event(s) avg | Events expected | Events available | Events to process | Input samples
-------------------|--------------|--------------|----------------|-----------------|------------------|-------------------|-----------------
'''
    
    for proc_pol in unique_proc_pol:
        process, polarization = proc_pol[:-3], proc_pol[-2:]
        c_chunks = chunks[chunks['proc_pol'] == proc_pol]
        
        n_samples_input = len(np.unique(c_chunks['location']))
        n_branches = len(c_chunks) if not is_m2m else len(np.unique(c_chunks['branch']))
        
        text += f"{n_branches:>18} | "
        text += f"{process:>12} | "
        text += f"{polarization:>12} | "
        text += f"{time_per_event[time_per_event['process'] == process]['tPE'][0]:14.4} | "
        text += f"{process_normalization[process_normalization['proc_pol'] == proc_pol]['n_events_expected'][0]:15.3} | "
        text += f"{process_normalization[process_normalization['proc_pol'] == proc_pol]['n_events_tot'][0]:16,} |"
        text += f"{np.sum(c_chunks[size_prop_name]):18,} | "
        text += f"{n_samples_input:>14} \n"
        
    return text