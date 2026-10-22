import os, os.path as osp
import subprocess

def provision_ild_config(basename:str|None=None):
    if basename is None:
        basename = osp.expandvars('$HOME')
    
    if not osp.isdir(osp.expandvars("$ILD_CONFIG_DIR")):
        ILD_CONFIG_DIR = osp.join(basename, 'ILDConfig')

        if not osp.isdir(ILD_CONFIG_DIR):
            cmd = f'git clone https://github.com/iLCSoft/ILDConfig.git "{ILD_CONFIG_DIR}"'
        else:
            cmd = f'cd "{ILD_CONFIG_DIR}" && git pull'

        proc = subprocess.run(cmd, check=True, shell=True)

        os.environ['ILD_CONFIG_DIR'] = ILD_CONFIG_DIR

def provision_sgv(basename:str|None=None):
    if basename is None:
        basename = osp.expandvars('$HOME')

    if not osp.isdir(osp.expandvars("$SGV_DIR")):
        SGV_DIR = osp.join(basename, 'ILDConfig')

        if not osp.isdir(SGV_DIR):
            proc = subprocess.run(f'wget https://github.com/ILDAnaSoft/ZHH/blob/898c8c302f8bfd2cf597d2ed434c43816ac7bafc/shell/sgv_install.sh -o "$HOME/sgv_install.sh" && mkdir -p "{SGV_DIR}" && source "$HOME/sgv_install.sh" "{SGV_DIR}"',
                                    check=True, shell=True)

        os.environ['SGV_DIR'] = SGV_DIR