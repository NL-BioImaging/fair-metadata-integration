import json
import os.path
import warnings
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import yaml
from rocrate.rocrate import ROCrate
from rocrate.model import ComputerLanguage, ContextEntity

from .preview import CratePreview

# Workflow Run Crate: the crate also describes a run of the workflow, with its parameter values
PROCESS_RUN_CRATE = 'https://w3id.org/ro/wfrun/process/0.5'
WORKFLOW_RUN_CRATE = 'https://w3id.org/ro/wfrun/workflow/0.5'


def create_ro_crate(dest_path, workflow_schema_filename, input_path, output_paths=[], gen_preview=True,
                    parameters=None):
    """Write a Workflow Run Crate to *dest_path* for a run of the bilayers workflow *workflow_schema_filename*.

    *parameters* are the values of the workflow's parameters in this run: a mapping, or
    the path of a YAML or JSON file of one, which is then also added to the crate.
    """
    crate = ROCrate()

    crate.metadata.extra_terms = {
        "organism_classification": "https://schema.org/taxonomicRange",
        "channel": "https://www.openmicroscopy.org/Schemas/Documentation/Generated/OME-2016-06/ome_xsd.html#Channel",
        "obo": "http://purl.obolibrary.org/obo/",
        "FBcv": "http://ontobee.org/ontology/FBcv/",
        "acquisition_method": {
            "@reverse": "https://schema.org/result",
            "@type": "@id",
        },
        "biological_entity": "https://schema.org/about",
        "biosample": "http://purl.obolibrary.org/obo/OBI_0002648",
        "preparation_method": "https://www.wikidata.org/wiki/Property:P1537",
        "specimen": "http://purl.obolibrary.org/obo/HSO_0000308",
    }

    output_entities = [add_data_entity(crate, path, dest_path) for path in output_paths]
    input_entity = add_data_entity(crate, input_path, dest_path)

    # main=True sets the root dataset's mainEntity and adds the Workflow RO-Crate
    # profile to the root dataset's conformsTo.
    workflow = crate.add_workflow(source=workflow_schema_filename,
                                  dest_path=os.path.basename(workflow_schema_filename),
                                  main=True, lang=get_bilayers_language(crate))

    # The Workflow RO-Crate profile ranges input/output over FormalParameter rather
    # than over the data entities themselves; each data entity is linked back to its
    # parameter with exampleOfWork.
    workflow['input'] = [add_formal_parameter(crate, input_entity, 'input')]
    if output_entities:
        workflow['output'] = [
            add_formal_parameter(crate, entity, 'output' if i == 0 else f'output_{i + 1}')
            for i, entity in enumerate(output_entities)
        ]
    schema_parameters = add_schema_parameters(crate, read_yaml(workflow_schema_filename))
    workflow.append_to('input', list(schema_parameters.values()))

    # The run itself: the workflow as instrument, the input data and parameter values as
    # object, the output data as result.
    run = crate.add(ContextEntity(crate, '#run', {'@type': 'CreateAction', 'name': f'Run of {workflow.id}'}))
    run['instrument'] = workflow
    run['object'] = [input_entity]
    if output_entities:
        run['result'] = output_entities
    if parameters is not None:
        values = parameters
        if not isinstance(parameters, Mapping):
            values = read_yaml(parameters)
            parameters_file = add_data_entity(crate, parameters, dest_path, copy=True)
            parameters_file['about'] = run
        run.append_to('object', add_parameter_values(crate, values, schema_parameters))
    for profile, name in ((PROCESS_RUN_CRATE, 'Process Run Crate'), (WORKFLOW_RUN_CRATE, 'Workflow Run Crate')):
        crate.root_dataset.append_to('conformsTo', crate.add(ContextEntity(crate, profile, {
            '@type': 'CreativeWork', 'name': name, 'version': '0.5'})))
    crate.root_dataset.append_to('mentions', run)

    if gen_preview:
        crate.add(CratePreview(crate))

    crate.write(dest_path)
    return crate


def add_data_entity(crate, path, crate_path, copy=False):
    """Add *path* to the crate: a folder (e.g. OME-Zarr) as a Dataset, a file (e.g. TIFF, CSV) as a File.

    Data inside *crate_path* is part of the crate where it is, and is not copied. Data
    outside it, such as the original input image, is referenced by its file URI rather
    than copied into the crate, unless *copy* is set: then it is copied to the crate root.
    """
    properties = get_encoding_format_property(crate, str(path))
    add = crate.add_dataset if os.path.isdir(path) else crate.add_file
    rel_path = relative_path_inside(path, crate_path)
    if rel_path is None and copy:
        rel_path = os.path.basename(str(path).rstrip('\\/'))
    if rel_path is None:
        return add(source=Path(path).resolve().as_uri(), properties=properties)
    return add(source=path, dest_path=rel_path, properties=properties)


def read_yaml(path):
    """The content of a YAML (or JSON, which is YAML too) file."""
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


# Bilayers parameter types with a schema.org data type other than Text
BILAYERS_DATA_TYPES = {'integer': 'Integer', 'float': 'Float', 'checkbox': 'Boolean'}


def add_schema_parameters(crate, schema):
    """Add a FormalParameter for each parameter the bilayers *schema* defines; map their names to them."""
    parameters = {}
    for parameter in (schema or {}).get('parameters') or []:
        if not isinstance(parameter, dict) or not parameter.get('name'):
            continue
        name = str(parameter['name'])
        properties = {
            '@type': 'FormalParameter',
            'name': name,
            'additionalType': BILAYERS_DATA_TYPES.get(parameter.get('type'), 'Text'),
            'valueRequired': not parameter.get('optional', False),
        }
        if parameter.get('description') or parameter.get('label'):
            properties['description'] = str(parameter.get('description') or parameter.get('label'))
        if parameter.get('default') is not None:
            properties['defaultValue'] = property_value(parameter['default'])
        parameters[name] = crate.add(ContextEntity(crate, f'#parameter-{quote(name)}', properties))
    return parameters


def add_parameter_values(crate, values, schema_parameters):
    """Add a PropertyValue for each parameter value in *values*, linked to the parameter it is the value of.

    *values* can be nested: a key that is not one of the workflow's parameters groups the
    parameters under it (e.g. by section). A value whose name is no parameter is still
    recorded, by its dotted path, but with a warning.
    """
    entities = []
    for name, value in flatten_parameter_values(values, schema_parameters):
        properties = {'@type': 'PropertyValue', 'name': name, 'value': property_value(value)}
        entity = crate.add(ContextEntity(crate, f'#value-{quote(name)}', properties))
        if name in schema_parameters:
            entity['exampleOfWork'] = schema_parameters[name]
        else:
            warnings.warn(f"'{name}' is not a parameter of the workflow")
        entities.append(entity)
    return entities


def flatten_parameter_values(values, schema_parameters, prefix=''):
    """The (name, value) of each parameter in the nested mapping *values*."""
    if not isinstance(values, Mapping):
        raise ValueError(f'Parameter values must be a mapping of names to values, not {type(values).__name__}')
    for key, value in values.items():
        name = prefix + str(key)
        if str(key) in schema_parameters:
            yield str(key), value
        elif isinstance(value, Mapping):
            yield from flatten_parameter_values(value, schema_parameters, name + '.')
        else:
            yield name, value


def property_value(value):
    """A parameter value as a JSON-LD value: scalars as they are, anything else as JSON text."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(value, default=str)


def relative_path_inside(path, folder):
    """The path of *path* relative to *folder*, or None if it is not inside it."""
    path, folder = Path(path).resolve(), Path(folder).resolve()
    if path == folder or not path.is_relative_to(folder):
        return None
    return path.relative_to(folder).as_posix()


# EDAM formats by file name ending (most specific first), with their name and IANA media type
EDAM_FORMATS = [
    (('.ome.tif', '.ome.tiff'), 'format_3727', 'OME-TIFF', 'image/tiff'),
    (('.zarr', '.zar'), 'format_3915', 'Zarr', None),
    (('.tif', '.tiff'), 'format_3591', 'TIFF', 'image/tiff'),
    (('.png',), 'format_3603', 'PNG', 'image/png'),
    (('.jpg', '.jpeg'), 'format_3579', 'JPEG', 'image/jpeg'),
    (('.h5', '.hdf5'), 'format_3590', 'HDF5', None),
    (('.csv',), 'format_3752', 'CSV', 'text/csv'),
    (('.tsv',), 'format_3475', 'TSV', 'text/tab-separated-values'),
    (('.xlsx',), 'format_3620', 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    (('.json',), 'format_3464', 'JSON', 'application/json'),
    (('.yaml', '.yml'), 'format_3750', 'YAML', 'application/yaml'),
    (('.xml',), 'format_2332', 'XML', 'application/xml'),
    (('.txt',), 'format_2330', 'Textual format', 'text/plain'),
]


def get_file_format(path):
    """The (EDAM format IRI, format name, IANA media type or None) of *path*, from its name, or None."""
    name = os.path.basename(str(path).rstrip('\\/')).lower()
    for endings, edam_format, format_name, media_type in EDAM_FORMATS:
        if name.endswith(endings):
            return f'http://edamontology.org/{edam_format}', format_name, media_type
    return None


def get_encoding_format_property(crate, path):
    """The encodingFormat of *path*: its media type and a reference to its EDAM format.

    As RO-Crate recommends, the format is a contextual entity (a WebPage) in the crate.
    """
    file_format = get_file_format(path)
    if not file_format:
        return None
    edam_iri, format_name, media_type = file_format
    crate.add(ContextEntity(crate, edam_iri, {'@type': 'WebPage', 'name': format_name}))
    encoding_format = {'@id': edam_iri}
    return {'encodingFormat': [media_type, encoding_format] if media_type else encoding_format}


def get_bilayers_language(crate):
    """Return the ComputerLanguage entity for a bilayers workflow specification.

    Identified by the Zenodo concept DOI, which is version-independent and
    resolves to the latest release of the specification.
    """
    return crate.add(ComputerLanguage(
        crate,
        identifier='https://doi.org/10.5281/zenodo.17652333',
        properties={
            'name': 'Bilayers',
            'alternateName': 'Bilayers workflow specification',
            'identifier': {'@id': 'https://doi.org/10.5281/zenodo.17652333'},
            'url': {'@id': 'https://github.com/bilayer-containers/bilayers'},
        },
    ))


def add_formal_parameter(crate, data_entity, name):
    """Add a FormalParameter describing *data_entity* and link the two together."""
    properties = {'@type': 'FormalParameter', 'name': name}
    # Bioschemas FormalParameter takes the format as a URL: the data entity's EDAM format, not its media type
    encoding_format = data_entity.as_jsonld().get('encodingFormat')
    format_ref = next((f for f in (encoding_format if isinstance(encoding_format, list) else [encoding_format])
                       if isinstance(f, dict)), None)
    if format_ref:
        properties['encodingFormat'] = format_ref
    parameter = crate.add(ContextEntity(crate, f'#{name}', properties))
    data_entity['exampleOfWork'] = parameter
    return parameter
