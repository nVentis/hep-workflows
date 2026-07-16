#!/bin/bash

# is_root_readable can take in two arguments:
# 1. (required) path to the root file
# 2. (optional) name of the TTree to check for existence.
# If the second argument is not provided, the function will only check if the file is readable.

is_root_readable() (
    # Assume python and uproot are available
    # They are by default on a key4hep stack
    
    local root_tree=${2:-None}

    if [[ "$root_tree" != "None" ]]; then
        local root_tree="'$root_tree'"
    fi

    local res=$(python <<EOF
import uproot
def root_file_readable(file_path:str, tree_name=None):
    res = False
    try:
        with uproot.open(file_path) as file:
            if isinstance(tree_name, str):
                tree = file[tree_name]
                rf_keys = tree.keys()

                return tree.num_entries > 0
            else:
                res = True
            
    except Exception as e:
        res = False
        
    return res

print(root_file_readable('${1}', ${root_tree}))
EOF
)
    
    if [ "$res" = "True" ]; then
        return 0
    else
        return 1
    fi
)