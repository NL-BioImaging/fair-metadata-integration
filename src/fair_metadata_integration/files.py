"""Write the files a crate records: the run's parameter values, and YAML in general."""
from collections.abc import Mapping
import os

import yaml

# The names the files a run's crate holds are given by default
WORKFLOW_CONFIG_NAME = 'config.yaml'
PARAMETERS_FILE_NAME = 'parameters.yaml'


def plain_value(value):
    """*value* as YAML can write it: scalars as they are, anything else (e.g. a Path) as text.

    Mappings, lists and tuples keep their structure, with their items made plain.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_value(item) for item in value]
    return str(value)


def write_yaml(path, data):
    """Write *data* to *path* as YAML, keeping the order it is given in; return *path*.

    The folder of *path* is created if it does not exist.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        yaml.safe_dump(data, file, sort_keys=False, allow_unicode=True)
    return path


def write_parameters(dest_path, values, file_name=PARAMETERS_FILE_NAME):
    """Write the parameter values of a run to *file_name* in the folder *dest_path*; return its path.

    *values* is a mapping of names to values, which can be grouped under keys of your own
    (e.g. by section); the path returned can be given to ``create_ro_crate(parameters=...)``.
    """
    if not isinstance(values, Mapping):
        raise ValueError(f'Parameter values must be a mapping of names to values, not {type(values).__name__}')
    return write_yaml(os.path.join(dest_path, file_name), plain_value(values))
