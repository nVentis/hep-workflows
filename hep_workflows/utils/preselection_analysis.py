from glob import glob
from dateutil import parser
import json
import numpy as np

DEFAULTS = {
    'PROD_NAME': '500-TDR_ws',
    'ILD_VERSION': 'ILD_l5_o1_v02',
    'BEAM_POLARIZATION': (-0.8, +0.3),
    'w_em_ep': {
        'LL': 0.315,
        'LR': 0.585,
        'RL': 0.035,
        'RR': 0.065
    }
}

def set_polarization(beamPolarization:tuple[float, float]):
    Peminus, Peplus = beamPolarization
    w_em_ep = w_prefacs(Peminus, Peplus)

    DEFAULTS['BEAM_POLARIZATION'] = (Peminus, Peplus)
    
    for i, key in enumerate(['LL', 'LR', 'RL', 'RR']):
        DEFAULTS['w_em_ep'][key] = w_em_ep[i]        

def get_polarization()->tuple[float, float]:
    return DEFAULTS['BEAM_POLARIZATION']

def get_polarization_weights()->dict[str, float]:
    return DEFAULTS['w_em_ep']

def get_preselection_meta(DATA_ROOT:str)->dict:
    metafile = glob(f'{DATA_ROOT}/htcondor_jobs*.json')[0]
    with open(metafile) as file:
        meta = json.load(file)
        
    return meta

def file_get_polarization(src_path:str)->tuple[int, int]:
    pol_e = -1 if '.eL.p' in src_path else (+1 if '.eR.p' in src_path else 0)
    pol_p = -1 if '.pL.' in src_path else (+1 if '.pR.' in src_path else 0)
    
    if pol_e == 0 or pol_p == 0:
        print(f'Warning: Encountered 0 polarization (?)')
        
    return pol_e, pol_p

def parse_sample_path(src_path:str,
                    PROD_NAME:str=DEFAULTS['PROD_NAME'],
                    ILD_VERSION:str=DEFAULTS['ILD_VERSION'])->tuple:
    loc = src_path.split(f'/{PROD_NAME}/')[1]
    loc = loc.split(f'/{ILD_VERSION}/')[0]
    polarization = file_get_polarization(src_path)
    
    return (loc, polarization)

def parse_json(json_path:str):
    with open(json_path, 'r') as file:
        content = json.load(file)
        
    return content

def get_preselection_summary_for_branch(
            DATA_ROOT:str,
            branch:int|str,
            PROD_NAME:str=DEFAULTS['PROD_NAME'],
            ILD_VERSION:str=DEFAULTS['ILD_VERSION']):
    
    branch = int(branch)
    
    try:
        with open(f'{DATA_ROOT}/{branch}/Source.txt') as file:
            src_path = file.read().strip()            
    except:
        src_path = ''
    
    try: 
        with open(f'{DATA_ROOT}/{branch}/zhh_FinalStateMeta.json') as jsonfile:
            fs_meta = json.load(jsonfile)
            process = fs_meta['processName']  
    except:
        process = ''
    
    try:
        with open(f'{DATA_ROOT}/stdall_{branch}To{branch+1}.txt') as file:
            # parse start time, end time, exit code to list of int/float (values)
            signals = ['start time    :', 'end time      :', 'job exit code :']
            temp = ["", "", ""]
            values:list[int|float] = [0, 0, 0]
            lsig = len(signals)
            
            for line in file.readlines():
                for i in range(lsig):
                    if line.startswith(signals[i]):
                        temp[i] = line.split(f'{signals[i]} ')[1].strip()
                    elif src_path == '' and '--global.LCIOInputFiles=' in line:
                        src_path = line.split('--global.LCIOInputFiles=')[1].strip().split(' --constant.OutputDirectory=')[0]
                        
            for i in [0, 1]:
                if temp[i] != '':
                    if ' (' in temp[i]:
                        temp[i] = temp[i].split(' (')[0]
                    
                    values[i] = float(parser.parse(temp[i]).timestamp())
            
            # exit code
            values[2] = int(temp[2])
                    
    except:
        values = [0, 0, 0]
    
    loc = ''
    polarization = (0, 0)
    if src_path != '':
        loc, polarization = parse_sample_path(src_path, PROD_NAME=PROD_NAME, ILD_VERSION=ILD_VERSION)
            
    return (branch, loc, process, polarization[0], polarization[1], src_path, values[0], values[1], values[1] - values[0], values[2])

def get_preselection_summary(DATA_ROOT:str, meta:dict)->np.ndarray:
    """_summary_

    Args:
        meta (dict): result returned from get_preselection_meta()

    Returns:
        np.ndarray: _description_
    """
    
    jobs = meta['jobs']
    dtype = [
        ('status', '<U16'),
        ('branch', 'I'),
        ('loc', '<U32'),
        ('process', '<U32'),
        ('pol_e', 'B'),
        ('pol_p', 'B'),
        ('src', '<U255'),
        ('tStart', 'f'),
        ('tEnd', 'f'),
        ('tDuration', 'f'),
        ('exitCode', 'i')]
    
    results = np.empty(0, dtype=dtype)

    for job_key in jobs:
        branch = jobs[job_key]['branches'][0]
        status = jobs[job_key]['status']
        
        ev = get_preselection_summary_for_branch(DATA_ROOT, branch)
        entry = (status, *ev)

        results = np.append(results, np.array([entry], dtype=dtype))
    
    return results

# https://doi.org/10.1016/j.physrep.2007.12.003
def w_prefacs(Pem, Pep):
    return (
        (1-Pem)*(1-Pep)/4, # LL
        (1-Pem)*(1+Pep)/4, # LR
        (1+Pem)*(1-Pep)/4, # RL
        (1+Pem)*(1+Pep)/4 # RR
    )

def combined_cross_section(processes:np.ndarray, process:str|list[str],
                           pol_em:float=-0.8, pol_ep:float=0.3)->float:
    
    if isinstance(process, list):
        return np.sum([combined_cross_section(processes, p, pol_em, pol_ep) for p in process])
    
    prefacs = w_prefacs(pol_em, pol_ep)
    cross_secs = np.zeros(4, dtype=float)
    
    for i, suffix in enumerate(['LL', 'LR', 'RL', 'RR']):
        entry = processes[processes['proc_pol'] == f'{process}_{suffix}']
        if len(entry) == 1:
            cross_secs[i] = entry['cross_sec'][0]
    
    return np.dot(prefacs, cross_secs)

def get_pol_key(pol_em:float, pol_ep:float)->str:
    key_em = ('L' if pol_em == -1. else ('R' if pol_em == 1. else 'N'))
    key_ep = ('L' if pol_ep == -1. else ('R' if pol_ep == 1. else 'N'))
    
    if key_em == 'N' or key_ep == 'N':
        raise Exception('Invalid polarization encountered')
    
    return key_em + key_ep

def get_w_pol(pol_em:int, pol_ep:int)->float:
    key = get_pol_key(pol_em, pol_ep)
    w_em_ep = get_polarization_weights()
    
    if not (key in w_em_ep):
        raise Exception(f'Unhandled polarization {key}')
    
    return w_em_ep[key]

def sample_weight(process_sigma_fb:float,
                  pol:tuple[int, int],
                  n_gen:int=1,
                  lum_inv_ab:float=2.)->float:
    
    w_pol = get_w_pol(*pol)    
    return process_sigma_fb * 1000 *lum_inv_ab * w_pol / n_gen