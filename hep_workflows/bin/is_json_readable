#!/bin/bash

is_json_readable() (
    # Assume python is available
    # It is by default on a key4hep stack

    local res=$(python <<EOF
from json import load
def json_file_readable(file_path:str):
    res = False
    try:
        with open(file_path) as jf:
            j = load(jf)
            
        res = True
        
    except Exception as e:
        res = False
        
    return res

print(json_file_readable('${1}'))
EOF
)    
    
    if [ "$res" = "True" ]; then
        return 0
    else
        return 1
    fi
)