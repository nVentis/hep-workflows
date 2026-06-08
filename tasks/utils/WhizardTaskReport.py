from typing import TypedDict
from glob import glob
import os.path as osp

class WhizardSample(TypedDict):
    sample_path: str
    whizard_version: str
    process: str
    sqrt_s: float
    beam1: str
    beam2: str
    beamPol1: float
    beamPol2: float
    n_gen: int
    cross_section: float
    cross_section_error: float
    cross_section_unit: str

WhizardTaskReport = list[WhizardSample]

def inspect_whizard_outputs(whizard_task_root:str)->WhizardTaskReport:
    """Inspects the output of a WhizardEventGeneration task
    and returns a list of WhizardSample objects by parsing
    the whizard.log files. Expects that each Whizard run
    succeeded and created a .slcio file in the task root dir.

    Args:
        whizard_task_root (str): root directory of the 
            WhizardEventGeneration task

    Raises:
        FileNotFoundError: _description_

    Returns:
        list[WhizardSample]: _description_
    """
    
    
    path = whizard_task_root
    results:list[WhizardSample] = []
    files = glob(f'{path}/*.Gwhizard-*/whizard.log')
    
    seps = [
        '|                               WHIZARD ',
        '| Process [scattering]: ',
        'sqrts =  ',
        '| Beam structure: ',
        '| Events: generating '
    ]
    
    for logf in files:        
        with open(logf, 'r') as f:
            lines = f.readlines()
        
        # Extracting the process name
        sample_path = f'{path}/{osp.basename(osp.dirname(logf))}.slcio'
        if not osp.isfile(sample_path):
            raise FileNotFoundError(f'File {sample_path} not found.')
        
        whizver = ''
        process = ''
        sqrt_s = 0.
        beam1 = ''
        beam2 = ''
        beamPol1 = 0.
        beamPol2 = 0.
        n_gen = 0
        cross_section = 0.
        cross_section_error = 0.
        cross_section_unit = ''
        
        for i in range(len(lines)):
            line = lines[i]
            
            if line.startswith(seps[0]):
                whizver = line.split(seps[0])[1].strip()
            elif line.startswith(seps[1]) and process == '':
                process = line.split(seps[1])[1].strip().replace('\'', '')
            elif line.startswith(seps[2]):
                sqrt_s = float(line.split(seps[2])[1].strip())
            elif line.startswith(seps[3]) and beam1 == '':
                beam1, beam2 = line[len(seps[3]):].split(',')[:2]
                beam2 = beam2.split(' =>')[0].strip()
                
                beamPol1 = float(lines[i+2].split('@(')[1].split(':')[0])
                beamPol2 = float(lines[i+4].split('@(')[1].split(':')[0])
            elif process != '' and line.startswith(process + ':'):
                a, b = lines[i+1].strip().split(' +- ')
                
                cross_section = float(a)
                cross_section_error = float(b.split(' ')[0])
                cross_section_unit = b.split(' ')[1].strip()
            elif line.startswith(seps[4]):
                n_gen = int(line.split(seps[4])[1].split(' ')[0])
                
        results.append(WhizardSample(sample_path=sample_path,
                                     whizard_version=whizver,
                                     process=process,
                                     sqrt_s=sqrt_s,
                                     beam1=beam1,
                                     beam2=beam2,
                                     beamPol1=beamPol1,
                                     beamPol2=beamPol2,
                                     n_gen=n_gen,
                                     cross_section=cross_section,
                                     cross_section_error=cross_section_error,
                                     cross_section_unit=cross_section_unit))
    
    return results
