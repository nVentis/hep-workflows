from .types import SGVOptions

def parse_item(value:str|bool|int|float):
    if isinstance(value, str):
        return f"'{value}'"
    elif isinstance(value, bool):
        return '.TRUE.' if value else '.FALSE.' 
    elif isinstance(value, int):
        return f'{value}'
    else:
        return f'{value:.8f}'
    
def parse_property_groups(properties_to_ensure:dict):
    properties = {}
    
    for prop, value in properties_to_ensure.items():
        if not (isinstance(value, str) or isinstance(value, float) or isinstance(value, int)):
            raise Exception(f'Unsupported type of property {prop}')
        
        section, key = prop.split('.')
        
        if section not in properties:
            properties[section] = {}
        
        properties[section][key] = value
    
    return properties

class SGVSteeringModifier:
    def __init__(self, steering_file:str, line_sep:str="\n"):
        self._steering_file = steering_file
        self._line_sep = line_sep
    
    def merge_properties(self, properties_to_ensure:SGVOptions)->str:
        """Reads the steering file, merges properties_to_ensure,
        i.e. a dictionary of configuration values, into it and
        returns the resulting steering file as string. 

        Args:
            properties_to_ensure (dict):
                desired configuration in format: group.key = value
                supports string, float and int values.
                example: properties_to_ensure = {
                    'global_generation_steering.CMS_ENE': 500,
                    'external_read_generation_steering.GENERATOR_INPUT_TYPE': 'STDH',
                    'external_read_generation_steering.INPUT_FILENAMES': 'input.stdhep'
                }

        Returns:
            _type_: _description_
        """
        result = ''
        current_section = None
        
        properties = parse_property_groups(properties_to_ensure)
        
        with open(self._steering_file) as sf:  
            for line_raw in sf:
                line = line_raw.strip()
                current_section_closing = False
                append_line = True
                
                if line.startswith('/'):
                    current_section_closing = True
                elif line.startswith('&'):
                    current_section = line[1:].split(' ')[0]
                
                # find existing active config entries, replace them
                if current_section is not None and current_section in properties:
                    for key in list(properties[current_section].keys()):
                        if line.startswith(key):
                            append_line = False
                            value = properties[current_section][key]
                            result += f'{key} = {parse_item(value)}{self._line_sep}'
                            
                            del properties[current_section][key]
                            
                    if not len(properties[current_section].keys()):
                        del properties[current_section]
                
                # find remaining config entries which should exist, but are not there --> add them
                if current_section_closing:
                    if current_section in properties:
                        for key, value in properties[current_section].items():
                            result += f"{key} = {parse_item(value)}{self._line_sep}"
                        
                        del properties[current_section]
                    
                    current_section = None 
                
                if append_line: 
                    result += line_raw# + self._line_sep
        
        return result