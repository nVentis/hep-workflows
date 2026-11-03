import os.path as osp

def splitext_mod(path:str)->tuple[str, str]:
    """Modified version of osp.splitext to identify .edm4hep.root as
    one file ending. 

    Args:
        path (str): _description_

    Returns:
        _type_: _description_
    """
    cand = list(osp.splitext(path))

    if len(cand) == 2 and cand[1] == '.root' and cand[0][-8:] == '.edm4hep':
        # is edm4hep file
        cand[0] = cand[0][:-8]
        cand[1] = '.edm4hep.root'

    return tuple(cand)