import os.path
from rocrate.rocrate import ROCrate
from rocrate.model import ComputerLanguage, ContextEntity


def create_ro_crate(dest_path, workflow_schema_filename, input_path, output_paths=[], gen_preview=True):
    crate = ROCrate(gen_preview=gen_preview)

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

    output_entities = [add_data_entity(crate, path) for path in output_paths]
    input_entity = add_data_entity(crate, input_path)

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

    crate.write(dest_path)
    return crate


def add_data_entity(crate, path):
    """Add *path* to the crate root: a folder (e.g. OME-Zarr) as a Dataset, a file (e.g. TIFF, CSV) as a File."""
    dest_path = os.path.basename(str(path).rstrip('\\/'))
    properties = get_additional_filetype_property(str(path))
    if os.path.isdir(path):
        return crate.add_dataset(source=path, dest_path=dest_path, properties=properties)
    return crate.add_file(source=path, dest_path=dest_path, properties=properties)


# EDAM formats by file name ending (most specific first)
EDAM_FORMATS = [
    (('.ome.tif', '.ome.tiff'), 'format_3727'),  # OME-TIFF
    (('.zarr', '.zar'), 'format_3915'),  # Zarr
    (('.tif', '.tiff'), 'format_3591'),  # TIFF
    (('.png',), 'format_3603'),  # PNG
    (('.jpg', '.jpeg'), 'format_3579'),  # JPG
    (('.h5', '.hdf5'), 'format_3590'),  # HDF5
    (('.csv',), 'format_3752'),  # CSV
    (('.tsv',), 'format_3475'),  # TSV
    (('.xlsx',), 'format_3620'),  # xlsx
    (('.json',), 'format_3464'),  # JSON
    (('.yaml', '.yml'), 'format_3750'),  # YAML
    (('.xml',), 'format_2332'),  # XML
    (('.txt',), 'format_2330'),  # Textual format
]


def get_additional_filetype_property(path):
    name = os.path.basename(str(path).rstrip('\\/')).lower()
    for endings, edam_format in EDAM_FORMATS:
        if name.endswith(endings):
            return {'additionalType': f'http://edamontology.org/{edam_format}'}
    return None


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
    format_ref = data_entity.get('additionalType')
    if format_ref:
        properties['format'] = {'@id': format_ref}
    parameter = crate.add(ContextEntity(crate, f'#{name}', properties))
    data_entity['exampleOfWork'] = parameter
    return parameter
