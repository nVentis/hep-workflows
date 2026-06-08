from os import name

if name != 'nt':
    from .BaseTask import BaseTask
    from .ShellTask import ShellTask
    
del name