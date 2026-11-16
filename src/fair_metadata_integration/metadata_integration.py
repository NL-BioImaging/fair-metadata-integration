import os.path
import re
import warnings
from collections.abc import Mapping
from functools import partial
from pathlib import Path
from urllib.parse import quote

import yaml
from rocrate.rocrate import ROCrate
from rocrate.model import ComputerLanguage, ContextEntity

from .bilayers import unknown_value_names
from .files import write_parameters, write_path_list
from .licenses import COMMON_LICENSES, DEFAULT_LICENSE
from .preview import CratePreview, zarr_attributes
from .provenance import add_acquisition, add_action_times, add_derivation, add_measurements, add_software

# Workflow Run Crate: the crate also describes a run of the workflow, with its parameter values.
# 0.6 is the version built on RO-Crate 1.3; 0.5 is built on 1.1
RUN_CRATE_VERSION = '0.6'
PROCESS_RUN_CRATE = f'https://w3id.org/ro/wfrun/process/{RUN_CRATE_VERSION}'
WORKFLOW_RUN_CRATE = f'https://w3id.org/ro/wfrun/workflow/{RUN_CRATE_VERSION}'
# The Bilayers specification release this package's configs follow
BILAYERS_VERSION = '1.0.0rc1'
BIOSCHEMAS_WORKFLOW_PROFILE = 'https://bioschemas.org/profiles/ComputationalWorkflow/1.0-RELEASE'
README_NAME = 'README.md'
# marks a README this package wrote, so a rerun rewrites it but never one written by hand
README_MARK = '<!-- written by fair-metadata-integration -->'
# The OME-NGFF specification, by version
NGFF_URL = 'https://ngff.openmicroscopy.org/{version}/'
# Terms for describing biological imaging metadata, added to the crate's JSON-LD context
EXTRA_TERMS = {
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
    "BioChemEntity": "https://schema.org/BioChemEntity",
}


def create_ro_crate(dest_path, workflow_schema_filename=None, input_paths=(), output_paths=(), metadata_paths=(),
                    parameters=None, copy_inputs=False, copy_outputs=False, gen_preview=True,
                    name=None, description=None, metadata_conforms_to=None, ome_version=None,
                    run_name=None, start_time=None, end_time=None, software=None, license=None):
    """Write an RO-Crate to *dest_path*; return the crate.

    With a bilayers workflow *workflow_schema_filename* it is a Workflow Run Crate for a run
    of that workflow. Without one, it describes just the data: *dest_path* and the files and
    folders given, e.g. an OME-Zarr store and the metadata files in it.

    *input_paths* and *output_paths* are the data the run consumed and produced; a single
    input can also be given as just its path. Instead of a path, an item can be a group of
    many files, as a mapping of its 'name', 'paths' and optionally 'description' and
    'list_file': a Dataset with those files as its parts, or listed in that CSV file
    (see :func:`add_data_group`). *metadata_paths* are further
    files describing the data, which are copied into the crate.

    *parameters* are the values of the workflow's parameters in this run: a mapping, or
    the path of a YAML or JSON file of one, which is then also added to the crate. They need
    a workflow to be the values of.

    Inputs and outputs outside *dest_path* are referenced by their file URI, unless
    *copy_inputs* / *copy_outputs* is set: then they are copied to the crate root.

    *name* and *description* are those of the crate's root dataset; the description defaults
    to what the crate holds. *license* is the license of its content, as RO-Crate requires:
    its URL, or a mapping of its 'url' and 'name' (default: CC BY 4.0). *metadata_conforms_to*
    is the schema the metadata files follow, as a mapping of its 'url' and optionally its
    'name' and 'version'. When *dest_path* is an OME-Zarr store, the root dataset conforms
    to its OME-NGFF version: *ome_version*, or else the one the store states.

    *run_name*, *start_time* and *end_time* (datetimes or ISO text) describe the run;
    *software* is what implements the workflow, as a mapping of its 'name' and optionally
    its 'url' and 'version'.
    """
    crate = build_ro_crate(dest_path, workflow_schema_filename, input_paths, output_paths, metadata_paths,
                           parameters, copy_inputs, copy_outputs, gen_preview, name, description,
                           metadata_conforms_to, ome_version, run_name, start_time, end_time, software, license)
    use_single_values(crate)
    crate.write(dest_path)
    return crate


def create_zarr_ro_crate(store_path, metadata_paths=(), metadata_conforms_to=None, description=None,
                         ome_version=None, gen_preview=True, source_paths=(), acquisition_metadata=(),
                         derivation=None, measurements=None, license=None):
    """Write an RO-Crate into the existing OME-Zarr store *store_path*, describing it; return the crate.

    Only ro-crate-metadata.json (with *gen_preview* the preview, and the 'list_file' of a group
    of sources) is written: the store itself is left as it is. The root dataset is the store,
    named after it, with its Zarr format and the OME-NGFF version it conforms to: *ome_version*,
    or else the one the store states. *description* defaults to what the store holds;
    *license* is as for :func:`create_ro_crate`.

    *metadata_paths* are files in the store describing it, e.g. its acquisition metadata;
    *metadata_conforms_to* is the schema they follow, as a mapping of its 'url' and
    optionally its 'name' and 'version'.

    Where the store came from: *source_paths* are the images it was made from, which it is
    based on, each a path or a group of paths as for :func:`create_ro_crate`;
    *acquisition_metadata* is the metadata of (some of) those images, as mappings, in which the instrument and acquisition times are looked up; *derivation* is how it was
    made from them, as a mapping of its 'name', and optionally its 'software' (a mapping of
    'name', 'url' and 'version'), 'start_time' and 'end_time'; *measurements* map the names
    of values measured on it to a value, or to a mapping of its 'value', 'description' and 'unit'.
    """
    if not os.path.isdir(store_path):
        raise ValueError(f'{store_path} is not an existing OME-Zarr store')
    outside = [str(path) for path in metadata_paths if relative_path_inside(path, store_path) is None]
    if outside:
        raise ValueError(f'Metadata files must be in the store {store_path}: {", ".join(outside)}')
    if description is None:
        has_labels = os.path.isdir(os.path.join(store_path, 'labels'))
        description = 'OME-Zarr image with labels' if has_labels else 'OME-Zarr image'
    crate = build_ro_crate(store_path, metadata_paths=metadata_paths, gen_preview=gen_preview,
                           name=store_name(store_path), description=description,
                           metadata_conforms_to=metadata_conforms_to, ome_version=ome_version, license=license)
    for path in metadata_paths:
        crate.get(relative_path_inside(path, store_path))['about'] = crate.root_dataset
    root = crate.root_dataset
    sources = [add_data_group(crate, item, partial(add_data_entity, crate, crate_path=store_path), store_path)
               for item in source_paths]
    if sources:
        root['isBasedOn'] = sources
    if acquisition_metadata:
        add_acquisition(crate, acquisition_metadata, sources or root)
    if derivation:
        action = add_derivation(crate, derivation, sources, root)
        if action.get('endTime'):
            root['datePublished'] = action['endTime']
    if measurements:
        add_measurements(crate, measurements, root)
    use_single_values(crate)
    crate.write(store_path)
    return crate


def build_ro_crate(dest_path, workflow_schema_filename=None, input_paths=(), output_paths=(), metadata_paths=(),
                   parameters=None, copy_inputs=False, copy_outputs=False, gen_preview=True,
                   name=None, description=None, metadata_conforms_to=None, ome_version=None,
                   run_name=None, start_time=None, end_time=None, software=None, license=None):
    """The crate :func:`create_ro_crate` writes, not written yet."""
    if parameters is not None and workflow_schema_filename is None:
        raise ValueError('Parameter values need a workflow to be the values of')
    if isinstance(input_paths, (str, os.PathLike, Mapping)):
        input_paths = [input_paths]
    crate = ROCrate()
    crate.metadata.extra_terms = dict(EXTRA_TERMS)
    if name is not None:
        crate.root_dataset['name'] = name
    if description is None:
        description = (f'A run of the workflow {os.path.basename(workflow_schema_filename)}, with its data'
                       if workflow_schema_filename is not None else 'Data and the metadata describing it')
    crate.root_dataset['description'] = description
    crate.root_dataset['license'] = add_license_entity(crate, license or DEFAULT_LICENSE)
    describe_ome_zarr_root(crate, dest_path, ome_version)

    output_entities = [add_data_group(crate, item, partial(add_data_entity, crate, crate_path=dest_path,
                                                           copy=copy_outputs), dest_path, copy_outputs)
                       for item in output_paths]
    input_entities = [add_data_group(crate, item, partial(add_data_entity, crate, crate_path=dest_path,
                                                          copy=copy_inputs), dest_path, copy_inputs)
                      for item in input_paths]
    schema = add_schema_entity(crate, metadata_conforms_to) if metadata_conforms_to else None
    for path in metadata_paths:
        entity = add_data_entity(crate, path, dest_path, copy=True)
        if schema is not None:
            entity['conformsTo'] = schema

    if workflow_schema_filename is not None:
        add_workflow_run(crate, workflow_schema_filename, input_entities, output_entities, parameters, dest_path,
                         run_name, start_time, end_time, software)
        add_readme(crate, dest_path)

    if gen_preview:
        crate.add(CratePreview(crate, properties={'name': 'Preview of the crate',
                                                  'description': 'Its entities and their properties, as a web page'}))
    return crate


def add_readme(crate, crate_path):
    """README.md about the crate, as Workflow RO-Crate recommends: written from the crate's name and description,
    unless the folder has a README.md of its own, which is then described as it is."""
    path = os.path.join(crate_path, README_NAME)
    if not os.path.exists(path) or Path(path).read_text(encoding='utf-8').startswith(README_MARK):
        root = crate.root_dataset
        lines = [README_MARK, f'# {root.get("name") or os.path.basename(os.path.abspath(crate_path))}', '',
                 str(root.get('description', '')), '',
                 f'This folder is an [RO-Crate](https://w3id.org/ro/crate): `{crate.metadata.id}` describes it, '
                 f'and `ro-crate-preview.html` shows that description as a web page.']
        os.makedirs(crate_path, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as file:
            file.write('\n'.join(lines) + '\n')
    readme = add_data_entity(crate, path, crate_path)
    readme['about'] = crate.root_dataset
    readme['encodingFormat'] = 'text/markdown'
    readme['description'] = 'What the crate holds'
    return readme


def use_single_values(crate):
    """Write a property with one value as that value, not a list of it, as RO-Crate 1.3 recommends."""
    for entity in crate.get_entities():
        properties = entity.properties()
        for key, value in properties.items():
            if isinstance(value, list) and len(value) == 1:
                properties[key] = value[0]


def add_workflow_run(crate, workflow_schema_filename, input_entities, output_entities, parameters, dest_path,
                     run_name=None, start_time=None, end_time=None, software=None):
    """Add the bilayers workflow and a run of it, which consumed *input_entities* and produced *output_entities*.

    The run's parameter values are not entities of the crate: the file holding them is, about the run.
    """
    # main=True sets the root dataset's mainEntity and adds the Workflow RO-Crate
    # profile to the root dataset's conformsTo.
    workflow = crate.add_workflow(source=workflow_schema_filename,
                                  dest_path=os.path.basename(workflow_schema_filename),
                                  main=True, lang=get_bilayers_language(crate))

    describe_workflow(crate, workflow, workflow_schema_filename, software)

    # The run itself: the workflow as instrument, the input data as object, the output data as result.
    run = crate.add(ContextEntity(crate, '#run', {
        '@type': 'CreateAction', 'name': run_name or f'Run of {workflow.id}',
        'description': f'A run of the workflow {workflow.id} on {len(input_entities)} input(s), '
                       f'giving {len(output_entities)} result(s)'}))
    run['instrument'] = workflow
    add_action_times(run, start_time, end_time)
    if input_entities:
        run['object'] = input_entities
    if output_entities:
        run['result'] = output_entities
    if parameters is not None:
        if isinstance(parameters, Mapping):
            parameters = write_parameters(dest_path, parameters)
        unknown = unknown_value_names(read_yaml(workflow_schema_filename), read_yaml(parameters) or {})
        if unknown:
            warnings.warn(f'Parameter values not in the workflow {workflow.id}: {", ".join(unknown)}')
        parameters_entity = add_data_entity(crate, parameters, dest_path, copy=True)
        parameters_entity['about'] = run
        parameters_entity['description'] = 'The parameter values of the run'
    for profile, name in ((PROCESS_RUN_CRATE, 'Process Run Crate'), (WORKFLOW_RUN_CRATE, 'Workflow Run Crate')):
        crate.root_dataset.append_to('conformsTo', crate.add(ContextEntity(crate, profile, {
            '@type': ['CreativeWork', 'Profile'], 'name': name, 'version': RUN_CRATE_VERSION})))
    crate.root_dataset.append_to('mentions', run)


def describe_workflow(crate, workflow, workflow_schema_filename, software=None):
    """Give the workflow what Process Run Crate and Bioschemas recommend: its format, size and description (from
    the config's first citation), and the version and url of the software it is part of."""
    workflow.properties().update(get_encoding_format_property(crate, workflow_schema_filename) or {})
    workflow['contentSize'] = str(os.path.getsize(workflow_schema_filename))
    citations = (read_yaml(workflow_schema_filename) or {}).get('citations') or [{}]
    tool = citations[0] if isinstance(citations[0], Mapping) else {}
    workflow['description'] = ': '.join(str(text) for text in (
        f'Bilayers workflow of {tool.get("name") or workflow.id}', tool.get('description')) if text)
    workflow['conformsTo'] = crate.add(ContextEntity(crate, BIOSCHEMAS_WORKFLOW_PROFILE, {
        '@type': ['CreativeWork', 'Profile'], 'name': 'Bioschemas ComputationalWorkflow profile',
        'version': '1.0-RELEASE'}))
    if software:
        workflow['isPartOf'] = add_software(crate, software)
        for key in ('version', 'url'):
            if software.get(key):
                workflow[key] = str(software[key])


def store_name(store_path):
    """The name of an OME-Zarr store: its folder name without '.ome.zarr' or '.zarr'."""
    name = os.path.basename(str(store_path).rstrip('\\/'))
    return re.sub(r'(\.ome)?\.zarr?$', '', name, flags=re.IGNORECASE)


def is_ome_zarr(path):
    """Whether *path* is named as a Zarr store, or is a folder with OME-Zarr attributes."""
    file_format = get_file_format(path)
    return (file_format is not None and file_format[1] == 'Zarr') or bool(zarr_attributes(Path(path)))


def get_ome_zarr_version(path):
    """The OME-NGFF version an OME-Zarr store states, or None.

    OME-Zarr 0.5 states it once for the store, earlier versions in each of its multiscales,
    plate or well; a bioformats2raw store, in each of its image series.
    """
    attributes = zarr_attributes(Path(path))
    if not attributes:
        return None
    if attributes.get('version'):
        return str(attributes['version'])
    for key in ('multiscales', 'plate', 'well'):
        value = attributes.get(key)
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, dict) and value.get('version'):
            return str(value['version'])
    if 'bioformats2raw.layout' in attributes:
        return get_ome_zarr_version(Path(path) / '0')
    return None


def describe_ome_zarr_root(crate, dest_path, ome_version=None):
    """If *dest_path* is an OME-Zarr store, give the root dataset its Zarr format and OME-NGFF version."""
    if ome_version is None and not is_ome_zarr(dest_path):
        return
    crate.root_dataset['encodingFormat'] = get_encoding_format_property(crate, '.zarr')['encodingFormat']
    store_version = get_ome_zarr_version(dest_path)
    if ome_version is None:
        ome_version = store_version
    elif store_version is not None and str(ome_version) != store_version:
        warnings.warn(f'{dest_path} states OME-NGFF version {store_version}, not the {ome_version} given')
    if ome_version is None:
        warnings.warn(f'The OME-NGFF version of {dest_path} is unknown')
        return
    crate.root_dataset.append_to('conformsTo', add_ngff_entity(crate, ome_version))


def add_ngff_entity(crate, ome_version):
    """The OME-NGFF specification of version *ome_version*, as a contextual entity."""
    return crate.add(ContextEntity(crate, NGFF_URL.format(version=ome_version), {
        '@type': ['CreativeWork', 'Profile'], 'name': f'OME-NGFF {ome_version}', 'version': str(ome_version)}))


def add_license_entity(crate, license):
    """The license *license*, its URL or a mapping of its 'url' and optionally 'name' and 'description', as a
    contextual entity; one of the COMMON_LICENSES is named and described by its URL alone."""
    if not isinstance(license, Mapping):
        license = {'url': license}
    known = next((common for common in COMMON_LICENSES if common['url'] == license.get('url')), {})
    license = known | {key: value for key, value in license.items() if value}
    if not license.get('url'):
        raise ValueError("A license needs a 'url'")
    properties = {'@type': 'CreativeWork', 'name': str(license.get('name') or license['url'])}
    if license.get('description'):
        properties['description'] = str(license['description'])
    return crate.add(ContextEntity(crate, str(license['url']), properties))


def add_schema_entity(crate, schema):
    """The schema data conforms to, from a mapping of its 'url' and optionally its 'name' and 'version'."""
    if not isinstance(schema, Mapping) or not schema.get('url'):
        raise ValueError("A schema to conform to needs a 'url'")
    properties = {'@type': ['CreativeWork', 'Profile']}
    for key in ('name', 'version'):
        if schema.get(key) is not None:
            properties[key] = str(schema[key])
    return crate.add(ContextEntity(crate, schema['url'], properties))


def add_data_entity(crate, path, crate_path, copy=False):
    """Add *path* to the crate: a folder (e.g. OME-Zarr) as a Dataset, a file (e.g. TIFF, CSV) as a File.

    Data inside *crate_path* is part of the crate where it is, and is not copied. Data
    outside it, such as the original input image, is referenced by its file URI rather
    than copied into the crate, unless *copy* is set: then it is copied to the crate root.
    An OME-Zarr store conforms to the OME-NGFF version it states.
    """
    properties = get_encoding_format_property(crate, str(path))
    add = crate.add_dataset if os.path.isdir(path) else crate.add_file
    rel_path = relative_path_inside(path, crate_path)
    if rel_path is None and copy:
        rel_path = os.path.basename(str(path).rstrip('\\/'))
    if rel_path is None:
        entity = add(source=Path(path).resolve().as_uri(), properties=properties)
    else:
        entity = add(source=path, dest_path=rel_path, properties=properties)
    add_ngff_conformance(crate, entity, path)
    # what RO-Crate recommends for every data entity, from the path; a caller can give better
    entity['name'] = os.path.basename(str(path).rstrip('\\/'))
    entity['description'] = data_description(path)
    if os.path.isfile(path):
        entity['contentSize'] = str(os.path.getsize(path))
    return entity


def data_description(path):
    """What *path* holds, as far as its name and content tell: e.g. 'OME-Zarr image', 'CSV file'."""
    if os.path.isdir(path):
        return 'OME-Zarr image' if is_ome_zarr(path) else 'Folder'
    file_format = get_file_format(path)
    return f'{file_format[1]} file' if file_format else 'File'


def add_data_group(crate, item, add_entity, crate_path=None, copy=False):
    """The entity *add_entity(path)* adds for a path; for a group of paths, a Dataset with their entities as its parts.

    A group is a mapping of its 'name', 'paths' and optionally 'description' and 'list_file'.
    The Dataset is the files' common folder (see :func:`group_folder_id`), or else a local
    '#dataset-' id. With a 'list_file' name, the files are not entities: their paths, relative
    to that folder, are written to that CSV file in *crate_path*, which is about the Dataset.
    """
    if not isinstance(item, Mapping):
        return add_entity(item)
    if not item.get('name') or not item.get('paths'):
        raise ValueError("A group of data needs a 'name' and 'paths'")
    list_file = item.get('list_file')
    if list_file and copy:
        raise ValueError('A group listed in a file is referenced, not copied')
    members = [] if list_file else [add_entity(path) for path in item['paths']]
    identifier = group_folder_id(item['paths'], crate_path, copy)
    # two groups in one folder must not merge into one entity
    if identifier is None or crate.get(identifier) is not None:
        identifier = f'#dataset-{quote(str(item["name"]))}'
    group = crate.add(ContextEntity(crate, identifier, {'@type': 'Dataset', 'name': str(item['name'])}))
    if item.get('description'):
        group['description'] = str(item['description'])
    if members:
        group['hasPart'] = members
    if list_file:
        list_path = write_path_list(os.path.join(crate_path, list_file), item['paths'], common_folder(item['paths']))
        list_entity = add_data_entity(crate, list_path, crate_path)
        list_entity['about'] = group
        list_entity['name'] = f'{item["name"]}: file list'
        list_entity['description'] = f'The paths of the {len(item["paths"])} files of {item["name"]}, relative to its folder'
        list_entity['contentSize'] = str(os.path.getsize(list_path))
    root_parts = crate.root_dataset.get('hasPart', [])
    # a '#' id is contextual, so its files must stay the root's parts to be data entities
    if not identifier.startswith('#') and all(member in root_parts for member in members):
        crate.root_dataset['hasPart'] = [part for part in root_parts if part not in members]
        crate.root_dataset.append_to('hasPart', group)
    return group


def group_folder_id(paths, crate_path=None, copy=False):
    """The id of the folder holding all *paths*: relative when it is in *crate_path*, else its file URI.

    None when that folder would be the crate itself: the paths are in its root, are copied
    there (*copy*), lie both in and outside it, or are on different drives.
    """
    folder = common_folder(paths)
    if folder is None:
        return None
    if crate_path is None:
        return folder.as_uri().rstrip('/') + '/'
    relative = relative_path_inside(folder, crate_path)
    if relative is not None:
        return relative + '/'
    any_inside = any(relative_path_inside(path, crate_path) is not None for path in paths)
    if copy or any_inside or folder == Path(crate_path).resolve():
        return None
    return folder.as_uri().rstrip('/') + '/'


def common_folder(paths):
    """The folder holding all *paths*, or None when there is none (they are on different drives)."""
    try:
        return Path(os.path.commonpath([Path(path).resolve().parent for path in paths]))
    except ValueError:
        return None


def add_ngff_conformance(crate, entity, path):
    """An OME-Zarr store conforms to the OME-NGFF version it states."""
    ome_version = get_ome_zarr_version(path) if os.path.isdir(path) else None
    if ome_version:
        entity.append_to('conformsTo', add_ngff_entity(crate, ome_version))


def read_yaml(path):
    """The content of a YAML (or JSON, which is YAML too) file."""
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f)


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
            'version': BILAYERS_VERSION,
            'identifier': {'@id': 'https://doi.org/10.5281/zenodo.17652333'},
            # as text: a reference would need an entity of its own
            'url': 'https://github.com/bilayer-containers/bilayers',
        },
    ))
