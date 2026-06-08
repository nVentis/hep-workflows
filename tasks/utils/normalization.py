import json
import numpy as np
import uproot as ur
import os.path as osp
from math import floor, ceil
from typing import Optional, List, Iterable, cast
from .PreselectionAnalysis import sample_weight
from copy import deepcopy

def get_process_normalization(
        processes:np.ndarray,
        samples:np.ndarray,
        RATIO_BY_TOTAL:Optional[float]=1.)->np.ndarray:
    """Returns a np.ndarray with

    Args:
        processes (np.ndarray): _description_
        samples (np.ndarray): _description_
        RATIO_BY_TOTAL (Optional[float], optional): If None, will use all the data. Defaults to 1..

    Returns:
        _type_: _description_
    """
    
    dtype = [
        ('process', '<U60'),
        ('proc_pol', '<U64'),
        ('cross_sec', 'f'),
        ('event_weight', 'f'),
        
        ('n_events_tot', 'l'),
        ('n_events_expected', 'f'),
        ('n_events_target', 'l')]
    
    results = np.empty(0, dtype=dtype)
    
    # Find the least represented proc_pol combination
    # First find n_events_tot for each proc_pol
    for p in processes:
        process, proc_pol, cross_sec = p['process'], p['proc_pol'], p['cross_sec']
        pol = p['pol_e'], p['pol_p']
        n_events_tot = samples[samples['proc_pol'] == proc_pol]['n_events'].sum()
            
        n_events_expected = sample_weight(cross_sec, pol, n_gen=1)
        event_weight = n_events_expected / n_events_tot
            
        results = np.append(results, np.array([
            (process, proc_pol, cross_sec, event_weight, n_events_tot, n_events_expected, 0)
        ], dtype=dtype))
        
    # Normalize by cross-section
    results = results[np.argsort(results['proc_pol'])]
    if RATIO_BY_TOTAL is None:
        results['n_events_target'] = results['n_events_tot']
    else:
        results['n_events_target'] = np.minimum(results['n_events_tot'], np.ceil(RATIO_BY_TOTAL * results['n_events_tot']))
    
    assert(np.sum(results['n_events_target'] < 0) == 0)
    
    return results

dtype_common = [
    ('branch', 'I'),
    ('sid', 'I'),
    ('process', '<U60'),
    ('proc_pol', '<U64'),
    ('location', '<U512')
]

def process_custom_statistics(pn:np.ndarray,
                              custom_statistics:list[tuple])->np.ndarray:
    
    for entry in custom_statistics:
        if len(entry) == 2:
            fraction, processes = entry
            if isinstance(processes, str):
                processes = [processes]
                
            reference = 'total'
        elif len(entry) == 3:
            fraction, processes, reference = entry
            reference = reference.lower()
        else:
            raise Exception('Cannot interpret custom_statistics')
        
        processes = np.unique(processes)
        mask = np.isin(pn['process'], processes)
        
        pn['n_events_target'][mask] = np.ceil(fraction*pn['n_events_' + ('tot' if reference == 'total' else 'expected')][mask])
        pn['n_events_target'][mask] = np.minimum(pn['n_events_target'][mask], pn['n_events_tot'][mask])
        
    return pn

CHUNK_SPLIT_MODES = {
    # splits one input LCIO file into multiple output files
    'ONE_TO_MANY': 0,
    
    # attempts to collect (if possible) all chunks of a single sample
    # into one output file.
    'MANY_TO_MANY': 1
}


def get_sample_chunk_splits(
    samples:np.ndarray,
    adjusted_time_per_event:np.ndarray,
    process_normalization:np.ndarray,
    custom_statistics:list[tuple]|None=None,
    existing_chunks:np.ndarray|None=None,
    MAXIMUM_TIME_PER_JOB:int=7200,
    split_mode:int=CHUNK_SPLIT_MODES['ONE_TO_MANY'],
    sample_groups:dict[str, dict[str, list[int]]]|None=None)->np.ndarray:
    """_summary_

    Args:
        samples (np.ndarray): _description_
        adjusted_time_per_event (np.ndarray): _description_. Defaults to None.
        process_normalization (np.ndarray): _description_.
        custom_statistics (Optional[List[tuple]], optional): list of entries of either (fraction:float, processes:list[str]) or
            (fraction:float, processes:list[str], reference:str<'total', 'expected'>)
        existing_chunks (Optional[np.ndarray], optional): Deprecated. Defaults to None.
        MAXIMUM_TIME_PER_JOB (int, optional): For splitting jobs, in seconds. Defaults to 7200 (2h).
        split_mode (int, optional): Determines the splitting behavior. Defaults to CHUNK_SPLIT_MODES['ONE_TO_MANY'].
        sample_groups (dict[str, dict[str, list[int]]]|None, optional): Can be provided if split_mode
            is CHUNK_SPLIT_MODES['MANY_TO_MANY']. { proc_pol: { src_bname: [sample IDs...] } } where all files  belonging
            to one src_bname will tried to be grouped together into one output file, if possible. the output will be numbered

    Returns:
        _type_: _description_
    """
    
    if existing_chunks is not None:
        raise Exception('The existing_chunks feature has been removed')

    if split_mode == CHUNK_SPLIT_MODES['ONE_TO_MANY']:
        return get_sample_chunk_splits_o2m(samples, adjusted_time_per_event,
                                           process_normalization, custom_statistics,
                                           MAXIMUM_TIME_PER_JOB)
    elif split_mode == CHUNK_SPLIT_MODES['MANY_TO_MANY']:
        if sample_groups is None:
            return get_sample_chunk_splits_m2m(samples, adjusted_time_per_event,
                                            process_normalization, custom_statistics,
                                            MAXIMUM_TIME_PER_JOB)
        else:
            return get_sample_chunk_splits_m2m_grouped(samples, adjusted_time_per_event,
                                            process_normalization, custom_statistics,
                                            MAXIMUM_TIME_PER_JOB, sample_groups)
    else:
        raise Exception(f'Unhandled split mode <{split_mode}>')

def get_sample_chunk_splits_o2m(samples:np.ndarray,
                                adjusted_time_per_event:np.ndarray,
                                process_normalization:np.ndarray,
                                custom_statistics:list[tuple]|None,
                                MAXIMUM_TIME_PER_JOB:int)->np.ndarray:
    
    dtype = deepcopy(dtype_common)
    dtype += [('n_chunks', 'I')]
    dtype += [('n_chunk_in_sample', 'I')]
    dtype += [('n_chunks_in_sample', 'I')]
    dtype += [('chunk_start', 'I')]
    dtype += [('chunk_size', 'I')]

    results = np.empty(0, dtype=dtype)

    pn = np.copy(process_normalization)
    atpe = adjusted_time_per_event

    if isinstance(custom_statistics, Iterable):
        pn = process_custom_statistics(pn, custom_statistics)

    n_branch_tot = 0

    for p in pn:
        n_target = p['n_events_target']
        
        if n_target > 0:
            c_chunks = []
            c_samples = samples[samples['proc_pol'] == p['proc_pol']]
            
            n_accounted = 0
            n_chunks = 0
            n_sample = 0
                
            max_chunk_size = 999999
            if atpe is not None:
                print(atpe, p)
                time_per_event = atpe['tPE'][atpe['process'] == p['process']]
                print(time_per_event)
                max_chunk_size = floor(MAXIMUM_TIME_PER_JOB/time_per_event)   
            
            while n_sample < len(c_samples) and n_accounted < n_target:
                sample = c_samples[n_sample] 
        
                n_chunks_in_sample = 0
                n_accounted_sample = 0
                n_tot_sample = sample['n_events']
                    
                while n_accounted < n_target and n_accounted_sample < n_tot_sample:
                    c_chunk_size = min(min(n_tot_sample - n_accounted_sample, max_chunk_size), n_target - n_accounted)
                    c_chunks.append((n_branch_tot, sample['sid'], p['process'], p['proc_pol'], sample['location'], n_chunks, n_chunks_in_sample, 0, n_accounted_sample, c_chunk_size))
                    
                    n_accounted += c_chunk_size
                    n_accounted_sample += c_chunk_size

                    n_chunks += 1
                    n_chunks_in_sample += 1
                    n_branch_tot += 1
                    
                n_sample += 1
                    
                if len(c_chunks) > 0:
                    results = np.append(results, np.array(c_chunks, dtype=dtype))
                    results['n_chunks_in_sample'][results['sid'] == sample['sid']] = n_chunks_in_sample
                    
                    c_chunks.clear()
                    
    return results

def get_sample_chunk_splits_m2m(samples:np.ndarray,
                                adjusted_time_per_event:np.ndarray,
                                process_normalization:np.ndarray,
                                custom_statistics:list[tuple]|None,
                                MAXIMUM_TIME_PER_JOB:int)->np.ndarray:
    
    dtype = deepcopy(dtype_common)
    dtype += [('sub_branch_size', 'I')]
    dtype += [('branch_size', 'I')]

    results = np.empty(0, dtype=dtype)

    pn = np.copy(process_normalization)
    atpe = adjusted_time_per_event

    if isinstance(custom_statistics, Iterable):
        pn = process_custom_statistics(pn, custom_statistics)

    n_branch_tot = 0

    for p in pn:
        n_target = p['n_events_target']
        
        if n_target > 0:
            c_chunks = []
            c_samples = samples[samples['proc_pol'] == p['proc_pol']]
            
            n_accounted = 0
            n_sample = 0
                
            max_chunk_size = 999999
            if atpe is not None:
                time_per_event = atpe['tPE'][atpe['process'] == p['process']]
                max_chunk_size = floor(MAXIMUM_TIME_PER_JOB/time_per_event)   
            
            n_in_branch = 0
                
            while n_accounted < n_target:
                sample = c_samples[n_sample]
                sample_size = sample['n_events']
                
                if n_in_branch + sample_size < max_chunk_size:
                    n_in_branch += sample_size
                else:
                    n_in_branch = 0
                    n_branch_tot += 1
                    
                c_chunks.append((n_branch_tot, sample['sid'], p['process'], p['proc_pol'], sample['location'], sample_size, 0))
                
                n_sample += 1
                n_accounted += sample_size
                
            if len(c_chunks) > 0:
                results = np.append(results, np.array(c_chunks, dtype=dtype))
                for branch in range(results['branch'].max() + 1):
                    results['branch_size'][results['branch'] == branch] = results['sub_branch_size'][results['branch'] == branch].sum()
                
                c_chunks.clear()
                    
    return results

def construct_sample_groups(
    reco_chunks:np.ndarray,
    analysis_samples:np.ndarray
)->dict[str, dict[str, list[int]]]:
    """Constructs a sample_groups dict based on a samples
    np.ndarray and a previous chunk_splits np.ndarray that
    was used in creating the sample.

    Args:
        reco_chunks (np.ndarray): _description_
        analysis_samples (np.ndarray): _description_

    Returns:
        dict[str, dict[str, list[int]]]: sample_groups for
            use with get_sample_chunk_splits_m2m_grouped
    """
    reco_chunk_2_analysis_sample_map = {}

    for sample_branch in range(len(analysis_samples)):
        reco_chunk = int(analysis_samples['location'][sample_branch].split('-')[-1].split('.slcio')[0])
        reco_chunk_2_analysis_sample_map[reco_chunk] = sample_branch

    grouped_branches = []

    source_sample_locations = np.unique(reco_chunks['location']).tolist()

    sample_groups = {}

    for loc in source_sample_locations:
        proc_pol = reco_chunks['proc_pol'][reco_chunks['location'] == loc][0]
        source_bname = osp.basename(loc).replace('.slcio', '')
        
        if not proc_pol in sample_groups:
            sample_groups[proc_pol] = {}
        
        reco_branches = reco_chunks['branch'][reco_chunks['location'] == loc].tolist()
        reco_branches.sort()
        
        sample_group = [ reco_chunk_2_analysis_sample_map[branch] for branch in reco_branches]    
        sample_groups[proc_pol][source_bname] = sample_group
        
        grouped_branches.append(reco_chunks['branch'][reco_chunks['location'] == loc].tolist())
        
    assert(len(reco_chunks) == len(np.concatenate(grouped_branches)) and
        len(reco_chunks) == len(analysis_samples))
    
    return sample_groups
    

def get_sample_chunk_splits_m2m_grouped(samples:np.ndarray,
                                adjusted_time_per_event:np.ndarray,
                                process_normalization:np.ndarray,
                                custom_statistics:list[tuple]|None,
                                MAXIMUM_TIME_PER_JOB:int,
                                sample_groups:dict[str, dict[str, list[int]]])->np.ndarray:
    
    dtype = deepcopy(dtype_common)
    dtype += [('sub_branch_size', 'I')]
    dtype += [('branch_size', 'I')]
    dtype += [('src_bname', '<U80')]

    results = np.empty(0, dtype=dtype)

    pn = np.copy(process_normalization)
    atpe = adjusted_time_per_event

    if custom_statistics is not None:
        pn = process_custom_statistics(pn, custom_statistics)

    n_branch_tot = -1

    for p in pn:
        process = p['process']
        proc_pol = p['proc_pol']
        n_target_total = p['n_events_target']
        n_accounted = 0
        
        if n_target_total > 0:
            assert(proc_pol in sample_groups)
            sample_group = sample_groups[proc_pol]
            c_chunks = []
            
            max_chunk_size = 999999
            if atpe is not None:
                time_per_event = atpe['tPE'][atpe['process'] == process][0] #np.average(atpe['tPE'][atpe['process'] == process])
                max_chunk_size = floor(MAXIMUM_TIME_PER_JOB/time_per_event)
            
            #print(proc_pol, max_chunk_size)
            
            for src_bname in sample_group:
                sample_ids = sample_group[src_bname]
                n_branch_tot += 1
                
                c_samples = samples[sample_ids]
                n_accounted_src_file = 0
                
                n_sample = 0
                n_in_branch = 0
                    
                while n_accounted < n_target_total and n_sample < len(c_samples):
                    sample = c_samples[n_sample]
                    sample_size = sample['n_events']
                    
                    if n_in_branch + sample_size < max_chunk_size:
                        n_in_branch += sample_size
                        n_accounted_src_file += sample_size
                    else:
                        n_in_branch = 0
                        n_branch_tot += 1
                        
                    c_chunks.append((n_branch_tot, sample['sid'], process, proc_pol, sample['location'], sample_size, 0, src_bname))
                    
                    n_sample += 1
                    n_accounted += sample_size
                    
                if len(c_chunks) > 0:
                    results = np.append(results, np.array(c_chunks, dtype=dtype))
                    for branch in range(results['branch'].max() + 1):
                        results['branch_size'][results['branch'] == branch] = results['sub_branch_size'][results['branch'] == branch].sum()
                    
                    c_chunks.clear()
                    
    return results

def get_chunks_factual(DATA_ROOT:str, chunks_in:np.ndarray, attach_time:bool=False):
    dtype_arr = chunks_in.dtype.descr + [('chunk_size_factual', 'I')]
    if attach_time:
        dtype_arr += [('runtime', 'I')]
    
    dtype_new = np.dtype(dtype_arr)
    
    chunks = np.zeros(chunks_in.shape, dtype_new)
    
    for name in chunks_in.dtype.names:
        chunks[name] = chunks_in[name]
    
    branches = chunks['branch']
    todelete = []
    for branch in branches:
        try:
            with open(f'{DATA_ROOT}/{branch}/zhh_FinalStateMeta.json') as jf:
                meta = json.load(jf)
                n_events = meta['nEvtSum']
                dt = meta['tEnd'] - meta['tStart']
                
            chunks['chunk_size_factual'][chunks['branch'] == branch] = n_events
            if attach_time:
                chunks['runtime'][chunks['branch'] == branch] = dt
        except:        
            try:
                if attach_time:
                    raise Exception('Not possible with attach_time=True')
                
                with cast(ur.WritableFile, ur.open(f'{DATA_ROOT}/{branch}/zhh_FinalStates.root')) as rf:
                    n_events = len(rf['event'].array())
                    
                chunks['chunk_size_factual'][chunks['branch'] == branch] = n_events
            except:
                print(f'Skipping chunk {branch} (unrecoverable), will be removed')
                chunks['chunk_size_factual'][chunks['branch'] == branch] = 0
                todelete.append(branch)    
    
    if len(todelete):
        chunks = np.delete(chunks, todelete, axis=0)
    
    return chunks
            
            