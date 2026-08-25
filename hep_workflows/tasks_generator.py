from typing import cast
from .utils import ShellTask, BaseTask
from .framework import HTCondorWorkflow, configurations
import os, shutil
import os.path as osp
import subprocess, law

class WhizardSteeringFileConstructor(BaseTask):
    """Builds the Sindarin steering files for all Whizard runs configured
    for the current tag and collects them, along with all other files
    required from each run's TEMPLATE_DIR, in a single output directory.

    Not a workflow task: it runs once and produces one directory that
    WhizardEventGeneration then branches over (one branch per .sin file).
    """

    def whizard_option_branches(self) -> dict[int, dict]:
        config = configurations.get(str(self.tag))
        assert(config.whizard_options is not None and len(config.whizard_options))

        whiz_ver = subprocess.check_output([f'whizard --version'], shell=True).split()[1].decode('utf-8')
        whizard_options = config.whizard_options

        branch_map = {}
        branch = 0

        for whizard_option in whizard_options:
            iters_per_polarization = whizard_option['iters_per_polarization'] if 'iters_per_polarization' in whizard_option else None

            for beamPol1, beamPol2, pol_key in [
                ('-1', '-1', 'eL.pL'),
                ('-1',  '1', 'eL.pR'),
                ( '1', '-1', 'eR.pL'),
                ( '1',  '1', 'eR.pR')
            ]:
                niters = 1 if iters_per_polarization is None else (0 if not pol_key in iters_per_polarization else iters_per_polarization[pol_key])
                if niters == 0:
                    continue

                for niter in range(niters):
                    properties = {
                        'COM_ENERGY': config.sqrt_s,
                        'WHIZARD_VERSION': whiz_ver,
                        'POLARIZATION_KEY': pol_key,
                        'BEAMPOL1': beamPol1,
                        'BEAMPOL2': beamPol2,
                        'PROCESS_NAME': whizard_option['process_name'],
                        'PROCESS_DEFINITION': whizard_option.get('process_definition', ''),
                        'TEMPLATE_DIR': whizard_option['template_dir'],
                        'SINDARIN_FILE': whizard_option['sindarin_file'],
                        'OUTPUT_INDEX': niter,
                        'NEVENTS': whizard_option.get('nevents', 100000)
                    }

                    branch_map[branch] = properties
                    branch += 1

        return branch_map

    def outputBasename(self, properties: dict) -> str:
        COM_ENERGY = int(properties['COM_ENERGY'])
        PROCESS_NAME = properties['PROCESS_NAME']
        WHIZARD_VERSION = properties['WHIZARD_VERSION']
        POLARIZATION_KEY = properties['POLARIZATION_KEY']
        OUTPUT_INDEX = properties['OUTPUT_INDEX']

        return f'E{COM_ENERGY}_TDR.P{PROCESS_NAME}.Gwhizard-{WHIZARD_VERSION}.{POLARIZATION_KEY}.{OUTPUT_INDEX}'

    def output(self):
        return self.local_directory_target()
    
    def sindarin_pre_hook(self, sindarin:str)->str:
        """Hook for subclasses to modify the sindarin file before writing it to disk and
        before replacing the $<PROP> placeholders with their values."""

        return sindarin

    def sindarin_post_hook(self, sindarin:str)->str:
        """Hook for subclasses to modify the sindarin file before writing it to disk and
        after replacing the $<PROP> placeholders with their values."""

        return sindarin

    def run(self):
        output_dir = self.output()
        output_dir.touch()

        for properties in self.whizard_option_branches().values():
            TEMPLATE_DIR = osp.expandvars(properties['TEMPLATE_DIR'])
            SINDARIN_FILE = properties['SINDARIN_FILE']

            # copy all other files contained in TEMPLATE_DIR, but never any *other* .sin
            # file: those are always branch-specific templates (like SINDARIN_FILE itself),
            # never meant to be copied verbatim - matching the same exclusion
            # WhizardEventGeneration.build_command() already applies on the job side
            for entry in os.listdir(TEMPLATE_DIR):
                if entry == SINDARIN_FILE or entry.endswith('.sin'):
                    continue

                src, dst = osp.join(TEMPLATE_DIR, entry), osp.join(output_dir.path, entry)
                if osp.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)

            # build the sindarin file for this branch
            with open(osp.join(TEMPLATE_DIR, SINDARIN_FILE), 'r') as f:
                sindarin = f.read()
            
            sindarin = self.sindarin_pre_hook(sindarin)

            basename = self.outputBasename(properties)
            sindarin = sindarin.replace('$OUTPUT_NAME', basename)
            for prop, value in properties.items():
                sindarin = sindarin.replace(f'${prop}', str(value))

            sindarin = self.sindarin_post_hook(sindarin)

            with open(osp.join(output_dir.path, f'{basename}.sin'), 'w') as f:
                f.write(sindarin)

class WhizardEventGeneration(ShellTask, HTCondorWorkflow, law.LocalWorkflow):
    def workflow_requires(self):
        reqs = super().workflow_requires()
        reqs['steering_files'] = WhizardSteeringFileConstructor.req(self)

        return reqs

    def requires(self):
        return WhizardSteeringFileConstructor.req(self)

    def runcard_dir(self)->law.LocalDirectoryTarget:
        return WhizardSteeringFileConstructor.req(self).output()

    @law.dynamic_workflow_condition
    def workflow_condition(self):
        return self.runcard_dir().exists()

    @workflow_condition.create_branch_map
    def create_branch_map(self) -> dict[int, str]:
        sin_files = sorted(f for f in os.listdir(self.runcard_dir().path) if f.endswith('.sin'))

        return dict(enumerate(sin_files))

    def outputBasename(self) -> str:
        return osp.splitext(cast(str, self.branch_data))[0]

    @workflow_condition.output
    def output(self):
        return [
            self.local_target(f'{self.outputBasename()}.slcio'),
            self.local_directory_target(self.outputBasename())
        ]

    def build_command(self, **kwargs):
        # prepare inputs
        output_file, output_dir = self.output()
        BaseTask.touch_parent(output_file)
        output_dir.touch()

        runcard_dir = self.runcard_dir().path
        SINDARIN_FILE = cast(str, self.branch_data)

        # copy the branch's sindarin file, as well as all other files in
        # runcard_dir (i.e. everything but the sibling branches' sindarin
        # files), to the working directory
        for entry in os.listdir(runcard_dir):
            if entry != SINDARIN_FILE and entry.endswith('.sin'):
                continue

            src, dst = osp.join(runcard_dir, entry), osp.join(output_dir.path, entry)
            if osp.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

        cmd =f"""rm -f "{output_file.path}"
echo "Starting Whizard at $(date)"
whizard "{SINDARIN_FILE}"
echo "Finished Whizard at $(date)"
mv "$(find . -maxdepth 1 -name '*.slcio' -print -quit)" "{output_file.path}" """.replace('\n', ' && ')

        return cmd

    def run(self, **kwargs):
        ShellTask.run(self, cwd=self.output()[1].path, keep_cwd=True, **kwargs)