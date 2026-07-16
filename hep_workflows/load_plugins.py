# Load entrypoints of plugins
# These may add configurations or task definitions

def load_plugins():
    from importlib.metadata import entry_points

    for ep in entry_points(group="hep_workflows.tasks"):
        # print(f'Registering hep_workflows plugin <{ep.name}>')

        register_fn = ep.load()
        register_fn()
    
load_plugins()