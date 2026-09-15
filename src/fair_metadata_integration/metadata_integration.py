import os.path
from rocrate.rocrate import ROCrate
from rocrate.model import ComputerLanguage, ContextEntity


def create_ro_crate(dest_path, workflow_schema_filename, input_path, output_paths=[]):
    crate = ROCrate()

    crate.metadata.extra_terms = {
        "organism_classification": "https://schema.org/taxonomicRange",
        "BioChemEntity": "https://schema.org/BioChemEntity",
        "channel": "https://www.openmicroscopy.org/Schemas/Documentation/Generated/OME-2016-06/ome_xsd.html#Channel",
        "obo": "http://purl.obolibrary.org/obo/",
        "FBcv": "http://ontobee.org/ontology/FBcv/",
        "acquisiton_method": {
            "@reverse": "https://schema.org/result",
            "@type": "@id",
        },
        "biological_entity": "https://schema.org/about",
        "biosample": "http://purl.obolibrary.org/obo/OBI_0002648",
        "preparation_method": "https://www.wikidata.org/wiki/Property:P1537",
        "specimen": "http://purl.obolibrary.org/obo/HSO_0000308",
    }

    output_entities = []
    for image_path in output_paths:
        rel_path = os.path.basename(image_path.rstrip('\\/'))
        output_entities.append(crate.add_dataset(
            source=image_path, dest_path=rel_path,
            properties=get_additional_filetype_property(image_path)))

    input_entity = crate.add_dataset(source=input_path,
                                     dest_path=os.path.basename(input_path.rstrip('\\/')),
                                     properties=get_additional_filetype_property(input_path))

    # main=True sets the root dataset's mainEntity and adds the Workflow RO-Crate
    # profile to the metadata descriptor's conformsTo.
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


def get_additional_filetype_property(path):
    ext = os.path.splitext(path)[1]
    ref = None
    if '.zar' in ext:
        ref = 'http://edamontology.org/format_3915'
    elif '.tif' in ext:
        ref = 'http://edamontology.org/format_3591'
    if ref:
        return {'additionalType': ref}
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
