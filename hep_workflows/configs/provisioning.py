"""Helpers for AnalysisConfiguration.setup() to provision dependencies beyond
CVMFS/key4hep. Both functions do nothing if the respective environment variable
(ILD_CONFIG_DIR, SGV_DIR) already points to an existing directory; otherwise the
dependency is installed to <basename>/<name> and the variable is set for this process.
basename defaults to $PROVISION_DIR, or $HOME if it is not set. They must be called after the key4hep
stack was sourced; SGV is compiled against it and must be reinstalled when the stack changes."""

import os, os.path as osp
import subprocess

SGV_INSTALL_SCRIPT = 'https://raw.githubusercontent.com/ILDAnaSoft/ZHH/898c8c302f8bfd2cf597d2ed434c43816ac7bafc/shell/sgv_install.sh'

def default_basename()->str:
    return os.environ.get('PROVISION_DIR') or osp.expanduser('~')

def provision_ild_config(basename:str|None=None):
    """Makes sure $ILD_CONFIG_DIR is an ILDConfig checkout, required by ddsim/k4run based
    simulation and reconstruction"""
    if osp.isdir(os.environ.get('ILD_CONFIG_DIR', '')):
        return

    ild_config_dir = osp.join(basename or default_basename(), 'ILDConfig')

    if not osp.isdir(ild_config_dir):
        subprocess.run(['git', 'clone', '--depth', '1', 'https://github.com/iLCSoft/ILDConfig.git', ild_config_dir], check=True)

    os.environ['ILD_CONFIG_DIR'] = ild_config_dir

def provision_sgv(basename:str|None=None):
    """Makes sure $SGV_DIR is an SGV installation (see sgv_install.sh) with the usesgvlcio executable,
    required by FastSimSGV"""
    if osp.isdir(os.environ.get('SGV_DIR', '')):
        return

    basename = basename or default_basename()
    sgv_dir = osp.join(basename, 'sgv')
    os.makedirs(basename, exist_ok=True)
    executable = osp.join(sgv_dir, 'tests', 'usesgvlcio.exe')

    if not osp.isfile(executable):
        # the install script is a sourced bash function, which requires a key4hep stack (LCIO)
        # Important: It prints errors that can be safely ignored (e.g. linking the optional
        # ROOT interface of pythia6). Success is defined by the executable existing.
        install = 'curl -fsSL --retry 3 --retry-all-errors --retry-delay 5 "$1" -o "$2" && source "$2" "$3"'
        subprocess.run(['bash', '-c', install, 'sgv_install', SGV_INSTALL_SCRIPT, osp.join(basename, 'sgv_install.sh'), sgv_dir],
                       check=True, stdin=subprocess.DEVNULL)

        if not osp.isfile(executable):
            raise RuntimeError(f'Installing SGV to {sgv_dir} failed: {executable} was not built. Note that the install needs a key4hep stack, and downloads pythia6 from pythia.org and root.cern.ch')

    os.environ['SGV_DIR'] = sgv_dir
