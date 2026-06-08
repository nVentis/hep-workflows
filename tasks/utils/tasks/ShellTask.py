import luigi, law, law.util, os, shutil
from .BaseTask import BaseTask
from typing import cast, Optional

def clear_path(path:str):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)

class ShellTask(BaseTask):
    """
    A task that provides convenience methods to work with shell commands, i.e., printing them on the
    command line and executing them with error handling.
    """
    cwd:Optional[str] = None

    # run_command_in_tmp: if True, directory will be deleted after successful execution
    run_command_in_tmp = True
    cleanup_tmp_on_error = False # set this to False to enable debugging
    
    # Builds the command which should be run using the executable
    # build_command runs after the tmp_dir/cwd and directory con-
    # taining the target exist
    def build_command(self, **kwargs)->str:
        # this method should build and return the command to run
        raise NotImplementedError

    def get_command(self, *args, **kwargs)->str:
        # this method is returning the actual, possibly cleaned command
        return self.build_command(*args, **kwargs)

    def allow_fallback_command(self, errors):
        # by default, never allow fallbacks
        return False

    def touch_output_dirs(self):
        # keep track of created uris so we can avoid creating them twice
        handled_parent_uris = set()

        for outp in law.util.flatten(self.output()):
            # get the parent directory target
            parent = None
            if isinstance(outp, law.SiblingFileCollection):
                parent = outp.dir
            elif isinstance(outp, law.FileSystemFileTarget):
                parent = outp.parent

            # create it
            if parent and parent.uri() not in handled_parent_uris:
                parent.touch()
                handled_parent_uris.add(parent.uri())

    def run_command(self, cmd:str, tmp_dir:law.LocalDirectoryTarget|None=None,
                    executable:str='/bin/bash', logfile:Optional[str]=None, highlighted_cmd=None, optional=False, **kwargs):
        """Runs the command cmd using subprocess.Popen

        Args:
            cmd (str): the command to run in executable
            tmp_dir (law.LocalDirectoryTarget|None):

            executable (str): the executable used for processing cmd
            logfile (str|None):
                if a string, all output (stdout & stderr) will be written
                    to this file. useful for debugging as otherwise log-
                    files are only written AFTER job execution.
                    the file will be created in cwd if no absolute path
                        is given
                if None, no real time writing of logs occurs.
            kwargs (dict): keyword arguments passed to subprocess.Popen
                if cwd is a member of the dict, it will be used as wor-
                    king directory and created, if it does not exist
                    if self.run_command_in_tmp, a temp directory will
                        be created if cwd does not exist.
                    if self.run_command_in_tmp == False, no cwd option
                        will be given to Popen

        Returns:
            dict: _description_
        """
        
        # proper command encoding
        cmd = (law.util.quote_cmd(cmd) if isinstance(cmd, (list, tuple)) else cmd).strip()

        # default highlighted command
        if not highlighted_cmd:
            highlighted_cmd = law.util.colored(cmd, 'cyan')

        # call it
        with self.publish_step(f'running {highlighted_cmd} ...'):
            p, lines = law.util.readable_popen(cmd, shell=True, executable=executable, **kwargs)
            if logfile is not None:
                with open(logfile, 'w') as lf:
                    for line in lines:
                        lf.write(line + "\n")
                        print(line)
            else:
                for line in lines:
                    print(line)

        # raise an exception when the call failed and optional is not True
        print('RETURN CODE:', p.returncode)
        if p.returncode != 0 and not optional:
            # when requested, make the tmp_dir non-temporary to allow for checks later on
            if tmp_dir and not self.cleanup_tmp_on_error:
                tmp_dir.is_tmp = False

            # raise exception
            raise ShellException(cmd, p.returncode, kwargs.get('cwd'))

        return p

    """
    @law.decorator.log
    @law.decorator.notify
    @law.decorator.localize
    """
    def run(self, keep_cwd:bool=False, **kwargs):
        # execute pre_run_command
        self.pre_run_command(**kwargs)
        
        # create all output directories
        self.touch_output_dirs()
        
        if 'cwd' in kwargs:
            self.cwd = kwargs['cwd']
        
        # create temp directory (if requested)
        tmp_dir:Optional[law.LocalDirectoryTarget] = None
        
        if self.run_command_in_tmp:
            if isinstance(self.cwd, str):
                tmp_dir = law.LocalDirectoryTarget(path=self.cwd)
                tmp_dir.touch()
                kwargs['cwd'] = tmp_dir.path
            else:
                tmp_dir = law.LocalDirectoryTarget(is_tmp=True)
                tmp_dir.touch()
                kwargs['cwd'] = tmp_dir.path
        self.publish_message(f'cwd: {kwargs.get("cwd", os.getcwd())}')

        # start command building and execution in a fallback loop
        errors = []
        while True:
            # get the command
            cmd = self.get_command(fallback_level=len(errors), **kwargs)
            if isinstance(cmd, tuple) and len(cmd) == 2:
                kwargs['highlighted_cmd'] = cmd[1]
                cmd = cmd[0]

            # run it
            try:
                self.run_command(cast(str, cmd), **kwargs)
                break
            except ShellException as e:
                errors.append(e)
                if self.allow_fallback_command(errors):
                    self.logger.warning(str(e))
                    self.logger.info(f'starting fallback command {len(errors)}')
                else:
                    raise e
            finally:
                if tmp_dir is not None and not keep_cwd:
                    if len(errors) == 0 or self.cleanup_tmp_on_error:
                        clear_path(cast(str, tmp_dir.path))

        self.post_run_command()

    def pre_run_command(self, **kwargs):
        return

    def post_run_command(self):
        return
    

class ShellException(Exception):

    def __init__(self, cmd, returncode, cwd=None):
        self.cmd = cmd
        self.returncode = returncode
        self.cwd = cwd or os.getcwd()

        msg = 'command execution failed'
        msg += f'\nexit code: {self.returncode}'
        msg += f'\ncwd      : {self.cwd}'
        msg += f'\ncommand  : {self.cmd}'

        super(ShellException, self).__init__(msg)
