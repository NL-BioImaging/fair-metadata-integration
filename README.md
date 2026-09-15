# fair-metadata-integration

Integrate and package all metadata into RO-Crate, linking to other metadata files.

Given a [Bilayers](https://github.com/bilayer-containers/bilayers) workflow
specification and the image data an analysis consumed and produced, this package
writes a [Workflow RO-Crate](https://w3id.org/workflowhub/workflow-ro-crate/1.0):
an `ro-crate-metadata.json` describing the run, alongside copies of the files it
describes.

## Installation

```bash
pip install fair-metadata-integration
```

Requires Python 3.12 or newer. [`rocrate`](https://pypi.org/project/rocrate/) is
installed automatically.

## Usage

```python
from fair_metadata_integration import create_ro_crate

create_ro_crate(
    dest_path="crate",
    workflow_schema_filename="config.yaml",
    input_path="input.ome.zarr",
    output_paths=["output.ome.zarr"],
)
```

- `dest_path` — directory the crate is written to, created if it does not exist.
- `workflow_schema_filename` — the Bilayers `config.yaml` describing the workflow.
- `input_path` — the input image (an OME-Zarr directory or a TIFF file).
- `output_paths` — the images the workflow produced. Each gets its own parameter.

The source files are copied into the crate, so `dest_path` ends up
self-contained:

```
crate/
├── config.yaml
├── input.ome.zarr/
├── output.ome.zarr/
└── ro-crate-metadata.json
```

### What the crate contains

The workflow specification is the crate's `mainEntity`, typed as a
`ComputationalWorkflow`, and the metadata descriptor declares the Workflow
RO-Crate profile:

```json
{
  "@id": "ro-crate-metadata.json",
  "@type": "CreativeWork",
  "about": { "@id": "./" },
  "conformsTo": [
    { "@id": "https://w3id.org/ro/crate/1.2" },
    { "@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.0" }
  ]
}
```

The workflow's `programmingLanguage` is a `ComputerLanguage` entity for the
Bilayers specification, identified by its Zenodo concept DOI
[`10.5281/zenodo.17652333`](https://doi.org/10.5281/zenodo.17652333), which
resolves to the latest release of the spec.

Inputs and outputs are modelled as `FormalParameter` entities carrying an
[EDAM](https://edamontology.org/) format IRI — `format_3915` for Zarr,
`format_3591` for TIFF. Each image dataset points back at the parameter it
realises via `exampleOfWork`:

```json
{
  "@id": "input.ome.zarr/",
  "@type": "Dataset",
  "additionalType": "http://edamontology.org/format_3915",
  "exampleOfWork": { "@id": "#input" }
}
```

The crate's JSON-LD context is extended with terms for describing biological
imaging metadata — `biosample`, `specimen`, `organism_classification`,
`preparation_method`, `channel` and others — so those properties can be added to
the crate's entities.

## Development

```bash
git clone https://github.com/NL-BioImaging/fair-metadata-integration.git
cd fair-metadata-integration
pip install -e ".[test]"
pytest
```

## License

MIT
