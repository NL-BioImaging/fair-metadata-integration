import os.path
from rocrate.rocrate import ROCrate
from rocrate.model import ContextEntity


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

    output_entity = None
    for image_path in output_paths:
        rel_path = os.path.relpath(image_path, dest_path)
        output_entity0 = crate.add_dataset(dest_path=rel_path)
        if output_entity is None:
            output_entity = output_entity0

    input_entity = crate.add_dataset(dest_path=os.path.basename(input_path.rstrip('\\/')))

    workflow = crate.add_workflow(dest_path=os.path.basename(workflow_schema_filename))
    workflow['input'] = input_entity
    if output_entity is not None:
        workflow['output'] = output_entity

    crate.write(dest_path)
    return crate
