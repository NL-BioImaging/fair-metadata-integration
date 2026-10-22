# fair-metadata-integration

Integrate and package all metadata into RO-Crate, linking to other metadata files.

Given a [Bilayers](https://github.com/bilayer-containers/bilayers) workflow
specification and the image data an analysis consumed and produced, this package
writes a [Workflow RO-Crate](https://w3id.org/workflowhub/workflow-ro-crate/1.1):
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
    input_path="data/input.ome.zarr",
    output_paths=["crate/output.ome.zarr"],
)
```

- `dest_path` — directory the crate is written to, created if it does not exist.
- `workflow_schema_filename` — the Bilayers `config.yaml` describing the workflow.
- `input_path` — the input image (an OME-Zarr directory or a TIFF file).
- `output_paths` — the images the workflow produced. Each gets its own parameter.
- `gen_preview` — write an `ro-crate-preview.html` alongside the metadata
  (default `True`).

Only the workflow specification is copied into the crate. Data inside
`dest_path`, such as the outputs the workflow wrote there, is part of the crate
where it is. Data outside it, typically the original input, is not copied but
referenced by its `file://` URI:

```
crate/
├── config.yaml
├── output.ome.zarr/
├── ro-crate-metadata.json
└── ro-crate-preview.html
```

`ro-crate-preview.html` is the human-readable
[RO-Crate Website](https://www.researchobject.org/ro-crate/specification/1.3/structure.html)
for the crate: a static HTML page (no scripts) with a section for every entity
and all its properties. References between entities link to each other's
section, so you can follow e.g. the workflow to an output parameter and on to the
file it describes; external URIs, types and property names link to their
definitions. Files and folders also get a summary of their content:

- CSV and TSV files: number of rows and columns, and the column names (with
  their types, for CellProfiler's `# header` line).
- OME-Zarr folders (Zarr v2 and v3): axes and units, the shape, chunks, data
  type and scale of each resolution level, channels, label images, and the plate
  layout or bioformats2raw image series.

Text files, which a browser would download rather than show, link to a
browsable view in `ro-crate-preview_files/`: CSV and TSV files as a table (the
first 1,000 rows), other text files such as YAML or CellProfiler pipelines as
text (the first 1,000,000 characters).

The preview is described in the metadata as a `CreativeWork` `about` the root
dataset, and is not part of the root dataset's `hasPart`.

### What the crate contains

The workflow specification is the crate's `mainEntity`, typed as a
`ComputationalWorkflow`. The metadata descriptor declares RO-Crate 1.3, and the
root dataset declares the Workflow RO-Crate 1.1 profile:

```json
{
  "@id": "ro-crate-metadata.json",
  "@type": "CreativeWork",
  "about": { "@id": "./" },
  "conformsTo": { "@id": "https://w3id.org/ro/crate/1.3" }
},
{
  "@id": "./",
  "@type": "Dataset",
  "conformsTo": [
    { "@id": "https://w3id.org/workflowhub/workflow-ro-crate/1.1" }
  ],
  "mainEntity": { "@id": "config.yaml" }
}
```

The workflow's `programmingLanguage` is a `ComputerLanguage` entity for the
Bilayers specification, identified by its Zenodo concept DOI
[`10.5281/zenodo.17652333`](https://doi.org/10.5281/zenodo.17652333), which
resolves to the latest release of the spec.

Folders (e.g. OME-Zarr) are `Dataset` entities, files `File` entities, with a
path relative to the crate when they are in it and their `file://` URI when
they are not. Their `encodingFormat` is an [EDAM](https://edamontology.org/)
format, from the file name: `format_3915` for Zarr, `format_3727` for OME-TIFF,
`format_3591` for TIFF, and PNG, JPEG, HDF5, CSV, TSV, xlsx, JSON, YAML, XML and
text. Files also give their IANA media type, and each EDAM format is a `WebPage`
contextual entity with its name, as RO-Crate recommends.

Inputs and outputs are modelled as `FormalParameter` entities, whose
`encodingFormat` is the same EDAM format. Each data entity points back at the
parameter it realises via `exampleOfWork`:

```json
{
  "@id": "Nuclei.csv",
  "@type": "File",
  "encodingFormat": ["text/csv", { "@id": "http://edamontology.org/format_3752" }],
  "exampleOfWork": { "@id": "#output" }
},
{
  "@id": "#output",
  "@type": "FormalParameter",
  "name": "output",
  "encodingFormat": { "@id": "http://edamontology.org/format_3752" }
},
{
  "@id": "http://edamontology.org/format_3752",
  "@type": "WebPage",
  "name": "CSV"
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

To inspect an example crate (OME-Zarr input, OME-Zarr and CellProfiler CSV
outputs), `test_example_crate` writes one and prints its path and that of its
preview; pytest keeps the folders of its last three runs. Run the test module as
a script to write it to a folder of your choice instead:

```bash
pytest -s -k test_example_crate
python tests/test_metadata_integration.py [folder]
```

### Releasing

The package version comes from the git tag, via
[`setuptools-scm`](https://setuptools-scm.readthedocs.io/); there is no version
to bump in `pyproject.toml`.

1. Optionally, do a dry run: run the *Publish to PyPI* workflow manually from
   the Actions tab. It builds, tests and uploads a development version (e.g.
   `0.2.4.dev2`) to [TestPyPI](https://test.pypi.org/project/fair-metadata-integration/).
2. Create a GitHub release with a new tag, e.g. `v0.2.4`, on the commit to
   release. Publishing the release builds, tests and uploads that version to
   [PyPI](https://pypi.org/project/fair-metadata-integration/).

PyPI never accepts the same version twice. If a release fails after uploading,
release a new version rather than reusing the tag.

## License

MIT
