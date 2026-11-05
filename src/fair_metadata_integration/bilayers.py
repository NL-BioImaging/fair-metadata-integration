"""Build a Bilayers workflow specification (config.yaml) for a run.

Where no hand written config exists for a tool, one can be generated from the values a
run used: every value becomes a parameter whose default is that value, so the config
records how the output was produced as well as what can be set.

When biomero-schema is installed, a config is checked by converting it with its Bilayers
adapter before it is written.
"""
from collections.abc import Mapping
import logging
import os

from .files import plain_value, write_yaml

logger = logging.getLogger(__name__)

# Bilayers format names that differ from the file name extension
BILAYERS_FORMATS = {'tif': 'tiff', 'jpg': 'jpeg', 'zarr': 'omezarr'}


def bilayers_config(name, parameters, inputs=(), outputs=(), citations=(), docker_image=None,
                    cli_command='', choices=None):
    """Return the Bilayers config of the workflow *name*.

    *parameters* maps the workflow's parameter names to the values the run used; values
    that are None are left out. *choices* maps the names of the parameters that are
    drop-downs to the values they offer. *inputs* and *outputs* are entries as
    :func:`image_entry` returns them; *docker_image* is a mapping of org, name, tag and
    platform.
    """
    choices = choices or {}
    return {
        'citations': list(citations),
        'docker_image': dict(docker_image or {}),
        'algorithm_folder_name': str(name),
        'exec_function': {
            'name': 'generate_cli_command',
            'cli_command': cli_command,
            'hidden_args': [],
        },
        'inputs': list(inputs),
        'outputs': list(outputs),
        'parameters': [parameter_entry(key, value, choices.get(key))
                       for key, value in parameters.items() if value is not None],
        'display_only': [],
    }


def image_entry(name, label=None, description='', subtype=(), formats=(), unique_string=('*',),
                section='inputs', depth=False, pyramidal=False, optional=False, file_count='single',
                cli_order=0):
    """Return an input or output entry describing an image."""
    return {
        'name': name,
        'type': 'image',
        'label': label or name.replace('_', ' ').capitalize(),
        'description': description,
        'subtype': list(subtype),
        'format': list(formats),
        'cli_tag': f'--{name}',
        'cli_order': cli_order,
        'default': '',
        'optional': optional,
        'file_count': file_count,
        'unique_string': list(unique_string),
        'section_id': section,
        'mode': 'beginner',
        'depth': depth,
        'timepoints': False,
        'tiled': False,
        'pyramidal': pyramidal,
    }


def parameter_entry(name, value, choices=None):
    """Return the parameter entry for one value: its type follows from the value, or from *choices*."""
    value = plain_value(value)
    entry = {
        'name': name,
        'label': name.replace('_', ' ').capitalize(),
        'description': '',
    }
    if choices:
        entry['type'] = 'dropdown'
        entry['options'] = [{'label': str(choice), 'value': plain_value(choice)} for choice in choices]
        entry['multiselect'] = False
    elif isinstance(value, bool):
        entry['type'] = 'checkbox'
        entry['append_value'] = False
    elif isinstance(value, int):
        entry['type'] = 'integer'
    elif isinstance(value, float):
        entry['type'] = 'float'
    else:
        entry['type'] = 'textbox'
        value = str(value)
    entry.update({
        'default': value,
        'cli_tag': f'--{name}',
        'optional': False,
        'mode': 'beginner',
    })
    return entry


def template_entries(config):
    """The inputs, outputs, parameters and display-only entries of the Bilayers *config*, each with a name."""
    return [entry for key in ('inputs', 'outputs', 'parameters', 'display_only') for entry in (config or {}).get(key) or []
            if isinstance(entry, dict) and entry.get('name')]


def value_path(entry):
    """Where a run's value for the template *entry* is in its parameter values: under its section_id, if it has one."""
    return tuple(str(key) for key in (entry.get('section_id'), entry['name']) if key)


def find_value(values, path):
    """(True, the value at *path* in the nested *values*), or (False, None) if it is not there."""
    for key in path:
        if not isinstance(values, Mapping) or key not in values:
            return False, None
        values = values[key]
    return True, values


def unknown_value_names(config, values, prefix=()):
    """The dotted names of the values in the nested *values* that are at no entry of the Bilayers *config*."""
    paths = {value_path(entry) for entry in template_entries(config)}
    unknown = []
    for key, value in values.items():
        path = prefix + (str(key),)
        is_section = any(len(known) > len(path) and known[:len(path)] == path for known in paths)
        if path not in paths and is_section and isinstance(value, Mapping):
            unknown.extend(unknown_value_names(config, value, path))
        elif path not in paths:
            unknown.append('.'.join(path))
    return unknown


def bilayers_format(path):
    """Return the Bilayers format name of an image file or folder, e.g. 'tiff' or 'omezarr'."""
    ext = os.path.splitext(str(path).rstrip('\\/'))[1].lower().lstrip('.')
    return BILAYERS_FORMATS.get(ext, ext)


def write_bilayers_config(path, config):
    """Validate *config* where possible and write it to *path* as YAML; return *path*."""
    validate_bilayers_config(config)
    return write_yaml(path, config)


def validate_bilayers_config(config):
    """Convert *config* with biomero-schema's Bilayers adapter, if it is installed.

    The conversion validates the result as a BIOMERO workflow schema and raises if the
    config does not describe a valid workflow. Without biomero-schema, nothing is checked
    and None is returned.
    """
    try:
        from biomero_schema.adapters import parse_descriptor
    except ImportError:
        logger.info('biomero-schema is not installed; the workflow config is not validated')
        return None
    return parse_descriptor(config, name=config.get('algorithm_folder_name'))
