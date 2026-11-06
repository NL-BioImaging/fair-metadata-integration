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
    input_paths=["data/input.ome.zarr"],
    output_paths=["crate/output.ome.zarr"],
    metadata_paths=["data/metadata.yaml"],
    parameters="parameters.yaml",
)
```

- `dest_path` — directory the crate is written to, created if it does not exist.
- `workflow_schema_filename` — the Bilayers `config.yaml` describing the workflow.
- `input_paths` — the data the workflow consumed (e.g. OME-Zarr directories or
  TIFF files). A single input can also be given as just its path.
- `output_paths` — the data the workflow produced.
- `metadata_paths` — further files describing the data
  (typically text: JSON, YAML, XML, CSV). They are part of the crate,
  and copied into its root when outside `dest_path`.
- `parameters` — the values the run used: the path of a YAML or JSON file, which
  is copied into the crate, or a `dict`, which is written to `parameters.yaml` in
  it. The file is `about` the run; its values are not entities of the crate.
  They are nested as `config.yaml` is: an entry with a `section_id` has its value
  under that key, so one name can be used in several sections:

  ```yaml
  pre_processing:
    normalisation: none
  registration:
    normalisation: true
  ```

  Every value is kept; values at no entry of `config.yaml` are listed in one
  warning (e.g. `registration.tiling`).
- `copy_inputs`, `copy_outputs` — copy the inputs, or the outputs, into the crate
  root when they are outside `dest_path` (default `False`: referenced, see below).
- `gen_preview` — write an `ro-crate-preview.html` alongside the metadata
  (default `True`).
- `name`, `description` — the name and description of the crate's root dataset.
- `metadata_conforms_to` — the schema the metadata files follow, as a `dict` of
  its `url` and optionally its `name` and `version`; each metadata file gets a
  `conformsTo` link to it.
- `ome_version` — when `dest_path` is itself an OME-Zarr store, the OME-NGFF
  version it conforms to (default: the version the store states; see below).
- `run_name`, `start_time`, `end_time` — the name of the run, and when it started
  and ended (datetimes or ISO text).
- `software` — the software implementing the workflow, as a `dict` of its `name`
  and optionally its `url` and `version`; the workflow `isPartOf` it.

`workflow_schema_filename` is optional: without it, the crate describes just the
data — the root dataset with the inputs, outputs and metadata files as its
parts — and has no workflow or run. `parameters` then cannot be given.

OME-Zarr stores, as inputs, outputs or as the crate itself, conform to the
OME-NGFF version they state (`conformsTo` e.g.
`https://ngff.openmicroscopy.org/0.5/`), read from `zarr.json` (0.5) or
`.zattrs` (0.4 and earlier).

### An RO-Crate in an OME-Zarr store

`create_zarr_ro_crate` describes an OME-Zarr store, written by something else,
with an RO-Crate in the store itself. Only `ro-crate-metadata.json` (and the
preview) is written; the store is left as it is:

```python
from fair_metadata_integration import create_zarr_ro_crate

create_zarr_ro_crate(
    "cells.ome.zarr",
    metadata_paths=["cells.ome.zarr/acquisition-metadata.yaml"],
    metadata_conforms_to={"url": "https://example.org/model.yaml", "name": "Imaging model", "version": "2.0"},
)
```

The root dataset is the store: named after it (`cells`), with the EDAM Zarr
format, the OME-NGFF version it conforms to — `ome_version`, or else the one the
store states (a warning if they differ, or if neither is known) — and a
`description`, by default "OME-Zarr image", or "OME-Zarr image with labels".
The metadata files must be in the store; they are `about` the store.

Where the store came from, as the Process Run Crate profile models it:

```python
create_zarr_ro_crate(
    "fused.ome.zarr",
    source_paths=["tiles/tile1.tif", "tiles/tile2.tif"],
    acquisition_metadata=[tile1_metadata, tile2_metadata],
    derivation={"name": "Fusion to OME-Zarr", "end_time": "2026-11-05T16:00:00",
                "software": {"name": "muvis-align", "url": "https://github.com/ccp-volume-em/muvis-align",
                             "version": "1.2"}},
    measurements={"ncc": 0.75, "nmi": {"value": 0.5, "description": "Registration NMI"}},
)
```

- `source_paths` — the images the store was made from: the store `isBasedOn`
  them, referenced by their `file://` URI and not part of the store.
- `acquisition_metadata` — metadata of (some of) the sources, as `dict`s: an
  `Image acquisition` `CreateAction` (`#acquisition`) with the sources as
  `result`, an `IndividualProduct` instrument from the manufacturer, model and
  serial number found in it (preferring fields under an instrument, microscope
  or device), and the earliest and latest acquisition date as start and end time.
  Keys are matched ignoring case and separators (`SerialNumber`, `serial_number`).
- `derivation` — how the store was made: a `CreateAction` (`#derivation`) with
  the sources as `object`, the store as `result` and the software as
  `instrument`; its end time is the store's `datePublished`.
- `measurements` — values measured on the store, as `PropertyValue`s of its
  `variableMeasured`: a value, or a `dict` of its `value`, `description` and `unit`.

### Helpers for writing a run's files

To package a run of a tool with no hand-written Bilayers config, generate one
from the values the run used, and write those values as its parameters file:

```python
from fair_metadata_integration import (WORKFLOW_CONFIG_NAME, bilayers_config, bilayers_format,
                                       create_ro_crate, image_entry, write_bilayers_config,
                                       write_parameters)

values = {"model": "MitoNet_v1", "confidence": 0.5}
config = bilayers_config(
    "empanada_3d", values,
    inputs=[image_entry("input_image", formats=[bilayers_format("data/input.tif")])],
    outputs=[image_entry("segmentation", formats=["omezarr"], section="outputs")],
    citations=[{"name": "empanada-napari", "doi": "10.1083/jcb.202208005"}],
    docker_image={"org": "ghcr.io/me", "name": "tool", "tag": "1.0", "platform": "linux/amd64"},
    cli_command="python run.py",
    choices={"model": ["MitoNet_v1", "MitoNet_v1_mini"]},
)
config_path = write_bilayers_config(f"crate/{WORKFLOW_CONFIG_NAME}", config)
parameters_path = write_parameters("crate", values)  # crate/parameters.yaml
create_ro_crate("crate", config_path, ["data/input.tif"], ["crate/output.ome.zarr"],
                parameters=parameters_path)
```

- `bilayers_config` makes every value a parameter whose default is that value,
  typed from it (`checkbox`, `integer`, `float`, `textbox`, or `dropdown` when it
  has `choices`); values that are `None` are left out. With `section`, the
  parameters get that `section_id`, so the run's values go under that key in
  `parameters.yaml`. `display_only` takes entries for values that are shown but
  not passed to the command, e.g. those of other tools of the run, made with
  `display_entry(name, value, section=...)`. `parameter_entry` and
  `image_entry` build single entries.
- `write_bilayers_config` validates the config by converting it with
  biomero-schema's Bilayers adapter when biomero-schema is installed, and writes
  it.
- `write_parameters` writes possibly nested values to `parameters.yaml`
  (`PARAMETERS_FILE_NAME`), with values YAML cannot hold (e.g. paths) as text;
  `plain_value` and `write_yaml` do this for any data.

### Command line

The same is available as the `create-ro-crate` command (or
`python -m fair_metadata_integration`):

```bash
create-ro-crate crate config.yaml \
    --input data/input.ome.zarr \
    --output crate/output.ome.zarr \
    --metadata data/metadata.yaml \
    --parameters parameters.yaml
```

`--input`, `--output` and `--metadata` each take one or more paths;
`--copy-inputs`, `--copy-outputs`, `--run-name`, `--start-time`, `--end-time`,
`--software NAME [URL [VERSION]]` and `--gen-preview` / `--no-gen-preview` match
the arguments above.
Run `create-ro-crate --help` for details.

Only the workflow specification, the parameters file and metadata files are
copied into the crate. Data inside `dest_path`, such as the outputs the workflow
wrote there, is part of the crate where it is. Data outside it, typically the
original input, is not copied but referenced by its `file://` URI (unless
`copy_inputs` or `copy_outputs` is set):

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
section, so you can follow e.g. the run to the workflow and on to the files it
produced; external URIs, types and property names link to their
definitions. Files and folders also get a summary of their content:

- CSV and TSV files: number of rows and columns, and the column names (with
  their types, for CellProfiler's `# header` line).
- The Bilayers `config.yaml`: citations, Docker image, command, and the
  inputs, outputs and parameters, with the values the run gave the parameters
  (read from the parameters file).
- OME-Zarr folders (Zarr v2 and v3): axes and units, the shape, chunks, data
  type and scale of each resolution level, channels, label images, and the plate
  layout or bioformats2raw image series.

Text files, which a browser would download rather than show, link to a
browsable view in `ro-crate-preview_files/`: CSV and TSV files as a table (the
first 1,000 rows), JSON and YAML files as a tree of keys and values you can
collapse, and other text files such as CellProfiler pipelines as text (the first
1,000,000 characters).

The preview is described in the metadata as a `CreativeWork` `about` the root
dataset, and is not part of the root dataset's `hasPart`.

### What the crate contains

The workflow specification is the crate's `mainEntity`, typed as a
`ComputationalWorkflow`. The metadata descriptor declares RO-Crate 1.3, and the
root dataset declares the Workflow RO-Crate 1.1 profile, and the
[Process Run Crate and Workflow Run Crate](https://www.researchobject.org/workflow-run-crate/)
0.5 profiles for the run (not shown):

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

The run is a `CreateAction`, mentioned by the root dataset, with the workflow
as `instrument`, the input data as `object` and the output data as `result`. The
workflow's parameters and the run's values are not entities of the crate: they
are in `config.yaml` and the parameters file, which is `about` the run:

```json
{
  "@id": "#run",
  "@type": "CreateAction",
  "name": "Run of config.yaml",
  "instrument": { "@id": "config.yaml" },
  "object": [{ "@id": "file:///data/input.ome.zarr/" }],
  "result": [{ "@id": "output.ome.zarr/" }]
},
{
  "@id": "parameters.yaml",
  "@type": "File",
  "about": { "@id": "#run" }
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

## Use of AI

Generative AI coding assistants were used in developing this software, including tests and documentation.
All changes are directed and approved by a maintainer, and checked by automated tests where applicable.

## License

[MIT]


[MIT]: http://opensource.org/licenses/MIT