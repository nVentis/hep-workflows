import json, os
import numpy as np
from glob import glob
from datetime import datetime

def get_dirs(path:str):
    return [ f.path for f in os.scandir(path) if f.is_dir() ]

def evaluate_runtime(DATA_ROOT:str,
                     bname:str,
                     WITH_EXIT_STATUS:bool=False):
    """_summary_

    Args:
        DATA_ROOT (str): _description_
        bname (str): base name of the result
        WITH_EXIT_STATUS (bool, optional): Requires --transfer-logs to be used when the law command is run. Defaults to False.

    Returns:
        _type_: _description_
    """
    
    branch = int(bname.split('-')[-1])
    
    with open(f'{DATA_ROOT}/{bname}/Source.txt') as file:
        src_path = file.read().strip()
        
    meta_file = glob(f'{DATA_ROOT}/{bname}/*FinalStateMeta.json')
    
    assert(len(meta_file) == 1)
    with open(meta_file[0]) as metafile:
        branch_meta = json.load(metafile)
        n_proc, process = branch_meta['nEvtSum'], branch_meta['processName']
        tEnd, tStart = branch_meta['tEnd'], branch_meta['tStart']
    
    value = -1
    if WITH_EXIT_STATUS:
        with open(f'{DATA_ROOT}/stdall_{branch}To{branch+1}.txt') as file:
            marker = 'job exit code :'
            
            for line in file.readlines():
                if line.startswith(marker):
                    value = int(line.split(f'{marker} ')[1].strip())
            
    return (branch, process, n_proc, src_path, tEnd - tStart, tStart, tEnd, value)

def get_runtime_analysis(DATA_ROOT:str|None=None,
                         chunks_factual:np.ndarray|None=None,
                         meta:dict|None=None,
                         WITH_EXIT_STATUS:bool=False)->np.ndarray:
    """_summary_

    Args:
        DATA_ROOT (str|None): _description_
        meta (dict|None): _description_

    Returns:
        np.ndarray: _description_
    """
    
    if chunks_factual is None and DATA_ROOT is None:
        raise Exception('Either chunks_factual or DATA_ROOT must be given')
    
    dtype = [
        ('branch', 'i'),
        ('process', '<U60'),
        ('n_processed', 'i'),
        ('src', '<U512'),
        ('tDuration', 'f')]
    
    results = []
    
    if chunks_factual is not None:
        results = chunks_factual[['branch', 'process', 'chunk_size_factual', 'location', 'runtime']].tolist()
    elif DATA_ROOT is not None:
        if meta is None:    
            metafile = glob(f'{DATA_ROOT}/htcondor_jobs*.json')[-1]
            
            with open(metafile) as file:
                meta = json.load(file)
        
        jobs = meta['jobs']
        dirs = get_dirs(DATA_ROOT)
    
        dtype += [('tStart', 'f')]
        dtype += [('tEnd', 'f')]
        dtype += [('exitCode', 'i')]
        
        for job_key in jobs:
            branch = jobs[job_key]['branches'][0]
            #if jobs[job_key]['status'] == 'finished':
            
            dir = list(filter(lambda a: a.endswith('-' + str(branch)) and not ('TMP-' in a), dirs))
            if not len(dir) == 1:
                raise Exception(f'Critical error: There are more than one result directories for branch <{branch}>. Please delete the unwanted one(s)')
            
            ev = evaluate_runtime(DATA_ROOT=DATA_ROOT, bname=os.path.basename(dir[0]), WITH_EXIT_STATUS=WITH_EXIT_STATUS)
            results.append(ev)
    else:
        raise Exception('No data source given')
    
    results = np.array(results, dtype=dtype)
                
    return results

def get_adjusted_time_per_event(runtime_analysis:np.ndarray,
                                 MAX_CAP:float|None=None,
                                 MIN_CAP:float=0.01,
                                 T0:int=0)->np.ndarray:
    
    """Average for each process (i.e. over each polarization) the processing
    runtime and apply the MIN/MAX_CAP values.

    Returns:
        np.ndarray: A named numpy array containing the columns
            process, tAvg, tMax, n_processes and tPE (time per event)
    """
    
    unique_processes = np.unique(runtime_analysis['process'])

    dtype = [
        ('process', '<U64'),
        ('tAvg', 'f'),
        ('tMax', 'f'),
        ('n_processed', 'i'),
        ('tPE', 'f')]

    results = np.zeros(len(unique_processes), dtype=dtype)

    for i, process in enumerate(unique_processes):
        # Average for
        subset = runtime_analysis[runtime_analysis['process'] == process]

        tAvg = np.average(subset['tDuration'])
        i_max = np.argmax(subset['tDuration'])
        tMax = subset['tDuration'][i_max]
        n_processed = subset['n_processed'].sum()
        tPE = (tMax - T0)/subset['n_processed'][i_max] #subset['tDuration'].sum()/ n_processed
        
        results['process'][i] = process
        results['tAvg'][i] = tAvg
        results['tMax'][i] = tMax
        results['n_processed'][i] = n_processed
        results['tPE'][i] = tPE
        
    if MAX_CAP is not None:
        results['tPE'][results['tPE'] > MIN_CAP] = np.minimum(results['tPE'], MAX_CAP)
        
    if MIN_CAP is not None:
        results['tPE'][results['tPE'] < MIN_CAP] = MIN_CAP
    
    return results

def sgv_runtime(logfile:str):
    """From a FastSimSGV logfile, returns the src/dst LCIO file,
    the number of events and the runtime in seconds.

    Args:
        logfile (str): _description_

    Returns:
        _type_: _description_
    """
    n_events = 0
    src_file = ''
    dst_file = ''
    
    with open(logfile, 'r') as f:
        for line in f:
            if line.startswith('  PROCESSING EVENT'):
                n_events = int(line[19:].split(' ...')[0].strip())
            elif line.startswith('SRC='):
                files = line[4:].split(' DST=')
                
                src_file = files[0].strip()
                dst_file = files[1].strip()
            elif not line.startswith('-- end --'):
                continue
            else:
                next(f)
                t_start = next(f).split(': ')[1].split('.')[0]
                t_end = next(f).split(': ')[1].split('.')[0]
                break
    
    t_start = datetime.strptime(t_start, '%d/%m/%Y %H:%M:%S')
    t_end   = datetime.strptime(t_end, '%d/%m/%Y %H:%M:%S')
    
    return src_file, dst_file, n_events, t_end - t_start 

def sgv_runtime_to_samples(samples:np.ndarray, logs:list[str], T0_SGV:int=3):
    """Uses a list of log files to create a modified copy of a samples np.ndarray
    (see ProcessIndex) with two additional columns about SGV runtime and time per
    event.

    Args:
        samples (np.ndarray): samples array from the RawIndex
        logs (list[str]): stdall_*.txt log s in the FastSimSGV directory
        T0_SGV (int, optional): SGV start up time. Defaults to 3.

    Returns:
        np.ndarray: samples_w_runtime
    """
    dtype = []
    for dt in samples.dtype.names:
        dtype.append((dt, samples.dtype[dt]))

    dtype += [('sgv_runtime', 'I')]
    dtype += [('sgv_time_per_event', 'f')]

    samples_w_runtime = np.zeros(len(samples), dtype=dtype)
    samples_w_runtime[list(samples.dtype.names)] = samples

    for log in logs:
        src_file, dst_file, n_events, dt = sgv_runtime(log)
        
        if not dst_file in samples['location']:
            print(f'Warning: dst_file <{dst_file}> was to be produced by SGV but could not be found in the samples index. Regenerate the index or check whether this is intended. File will be skipped.')
        else:
            samples_w_runtime['sgv_runtime'][samples_w_runtime['location'] == dst_file] = dt.seconds

    samples_w_runtime['sgv_time_per_event'] = (samples_w_runtime['sgv_runtime'] - T0_SGV) / samples_w_runtime['n_events']
    
    return samples_w_runtime