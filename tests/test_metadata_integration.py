import json
import os
from pathlib import Path
import pytest

from fair_metadata_integration.metadata_integration import create_ro_crate, get_file_format
from fair_metadata_integration.preview import ome_zarr_details, table_details


BILAYERS_CONFIG = """\
citations:
  - name: "Empanada"
    doi: "10.1083/jcb.202208005"
    license: "Apache-2.0"
    description: "Panoptic segmentation of organelles in volume electron microscopy"

docker_image:
  org: "czii"
  name: "empanada-napari"
  tag: "latest"
  platform: "linux/amd64"

algorithm_folder_name: "empanada_inference"

exec_function:
  name: "generate_cli_command"
  cli_command: "python -m empanada.inference"
  hidden_args: []

inputs:
  - name: input_image
    type: image
    cli_tag: "--image"
    cli_order: 1

outputs:
  - name: segmentation
    type: image
    cli_tag: "--output"
    cli_order: 2

parameters:
  - name: model
    type: string
    cli_tag: "--model"
    default: "MitoNet_v1_mini"

display_only: []
"""


def make_bilayers_config(path: Path) -> Path:
    """Write a minimal bilayers config.yaml to *path* and return it."""
    config = path / "config.yaml"
    config.write_text(BILAYERS_CONFIG)
    return config


def make_ome_zarr_dirs(path: Path) -> tuple[Path, Path]:
    """Create an input ome-zarr directory under *path*, and an output one in the crate at *path*/crate.

    As a workflow does: it reads its input from wherever it is, and writes its output into the crate.
    """
    input_zarr = path / "input.ome.zarr"
    output_zarr = path / "crate" / "output.ome.zarr"
    # Nested content, so tests can check the tree is not copied into the crate.
    (input_zarr / "0").mkdir(parents=True)
    (input_zarr / ".zattrs").write_text('{"multiscales": []}')
    (input_zarr / "0" / "0.0.0").write_bytes(b"\x01\x02\x03")
    output_zarr.mkdir(parents=True)
    (output_zarr / ".zattrs").write_text('{"segmentation": true}')
    return input_zarr, output_zarr


def uri(path: Path) -> str:
    """The @id of data referenced from outside the crate: its file URI, with a '/' for a folder."""
    return path.resolve().as_uri() + ("/" if path.is_dir() else "")


def write_json(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content))


MULTISCALES = {
    "name": "cells",
    "axes": [
        {"name": "c", "type": "channel"},
        {"name": "y", "type": "space", "unit": "micrometer"},
        {"name": "x", "type": "space", "unit": "micrometer"},
    ],
    "datasets": [
        {"path": "0", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 0.5, 0.5]}]},
        {"path": "1", "coordinateTransformations": [{"type": "scale", "scale": [1.0, 1.0, 1.0]}]},
    ],
}
OMERO = {"channels": [{"label": "DAPI", "color": "0000FF"}, {"label": "GFP", "color": "00FF00"}]}


def make_ome_zarr_v2(path: Path) -> Path:
    """An OME-Zarr 0.4 (Zarr v2) image with two resolution levels, two channels and a label image."""
    write_json(path / ".zattrs", {"multiscales": [{"version": "0.4", **MULTISCALES}], "omero": OMERO})
    write_json(path / "0" / ".zarray", {"shape": [2, 512, 512], "chunks": [1, 256, 256], "dtype": "<u2"})
    write_json(path / "1" / ".zarray", {"shape": [2, 256, 256], "chunks": [1, 256, 256], "dtype": "<u2"})
    write_json(path / "labels" / ".zattrs", {"labels": ["nuclei"]})
    return path


def make_ome_zarr_v3(path: Path) -> Path:
    """An OME-Zarr 0.5 (Zarr v3) image."""
    write_json(path / "zarr.json", {"zarr_format": 3, "node_type": "group", "attributes": {
        "ome": {"version": "0.5", "multiscales": [MULTISCALES], "omero": OMERO}}})
    for level, size in (("0", 512), ("1", 256)):
        write_json(path / level / "zarr.json", {
            "zarr_format": 3, "node_type": "array", "shape": [2, size, size], "data_type": "uint16",
            "chunk_grid": {"name": "regular", "configuration": {"chunk_shape": [1, 256, 256]}}})
    return path


class TestCreateRoCrate:
    @pytest.fixture()
    def bilayers_config(self, tmp_path: Path) -> Path:
        return make_bilayers_config(tmp_path)

    @pytest.fixture()
    def ome_zarr_dirs(self, tmp_path: Path) -> tuple[Path, Path]:
        return make_ome_zarr_dirs(tmp_path)
    
    def test_create_ro_crate(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """create_ro_crate writes a valid RO-Crate with all expected entities."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        dest.mkdir(exist_ok=True)

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        assert (dest / "ro-crate-metadata.json").exists()

        ids = self._read_ids(dest)
        # rocrate normalises paths to forward-slashes with a trailing '/'.
        assert any(eid == "output.ome.zarr/" for eid in ids), (
            f"Output zarr not found in crate entities: {ids}"
        )
        # Entities must live inside the crate root, never above it.
        assert not any(eid.startswith("../") for eid in ids), (
            f"Crate contains entities outside the crate root: {ids}"
        )
        assert any("config.yaml" in eid for eid in ids), (
            f"Bilayers config.yaml not found in crate entities: {ids}"
        )
        # The input, outside the crate, is referenced by its file URI.
        assert uri(input_zarr) in ids

    def test_workflow_ro_crate_profile(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """The crate declares the Workflow RO-Crate profile correctly."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        dest.mkdir(exist_ok=True)

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        entities = self._read_entities(dest)

        # The metadata descriptor declares the base spec; the root dataset
        # declares the Workflow RO-Crate profile, described by a Profile entity.
        assert entities["ro-crate-metadata.json"]["conformsTo"] == {
            "@id": "https://w3id.org/ro/crate/1.3"
        }
        profile_id = "https://w3id.org/workflowhub/workflow-ro-crate/1.1"
        assert {"@id": profile_id} in entities["./"]["conformsTo"]
        assert "Profile" in entities[profile_id]["@type"]

        # The root dataset must point at the workflow as its main entity.
        assert entities["./"]["mainEntity"] == {"@id": "config.yaml"}

        workflow = entities["config.yaml"]
        assert "ComputationalWorkflow" in workflow["@type"]

        # input/output must reference FormalParameter entities, not the datasets.
        for prop in ("input", "output"):
            for ref in workflow[prop]:
                assert entities[ref["@id"]]["@type"] == "FormalParameter", (
                    f"workflow {prop} '{ref['@id']}' is not a FormalParameter"
                )

        # Each dataset links back to the parameter it is an example of.
        assert entities[uri(input_zarr)]["exampleOfWork"] == {"@id": "#input"}
        assert entities["output.ome.zarr/"]["exampleOfWork"] == {"@id": "#output"}

        # Parameters give their EDAM format with the Bioschemas encodingFormat property.
        assert entities["#input"]["encodingFormat"] == {"@id": "http://edamontology.org/format_3915"}
        assert "format" not in entities["#input"]

        # The language must describe bilayers, not CWL, and must be identified by
        # a resolvable persistent identifier rather than an invented one.
        lang = entities[workflow["programmingLanguage"]["@id"]]
        assert lang["@type"] == "ComputerLanguage"
        assert lang["name"] == "Bilayers"
        assert lang["@id"] == "https://doi.org/10.5281/zenodo.17652333"

    def test_data_outside_the_crate_is_referenced_not_copied(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """Data inside the crate stays where it is; data outside it is referenced by its file URI."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        dest.mkdir(exist_ok=True)

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        assert (dest / "config.yaml").read_text() == BILAYERS_CONFIG
        assert not (dest / "input.ome.zarr").exists()
        assert (dest / "output.ome.zarr" / ".zattrs").exists()
        ids = self._read_ids(dest)
        assert uri(input_zarr) in ids
        assert "output.ome.zarr/" in ids

        # Every entity with a relative @id is backed by a file that is actually in the crate.
        for eid in ids:
            if eid.startswith(("#", "http", "file:")) or eid == "./":
                continue
            assert (dest / eid).exists(), f"entity '{eid}' has no file in the crate"

    def test_data_in_a_subfolder_of_the_crate_keeps_its_place(self, tmp_path, bilayers_config, ome_zarr_dirs):
        input_zarr, _ = ome_zarr_dirs
        dest = tmp_path / "crate"
        table = dest / "tables" / "Nuclei.csv"
        table.parent.mkdir(parents=True)
        table.write_text("ObjectNumber,Area\n1,42\n")

        create_ro_crate(str(dest), str(bilayers_config), str(input_zarr), [str(table)])

        assert "tables/Nuclei.csv" in self._read_ids(dest)
        assert not (dest / "Nuclei.csv").exists()

    def test_file_input_and_outputs_are_files(self, tmp_path, bilayers_config):
        """Files (TIFF, CSV) are File entities, not Dataset folders, inside the crate or referenced."""
        input_tiff = tmp_path / "input.tif"
        input_tiff.write_bytes(b"II*\x00input")
        dest = tmp_path / "crate"
        dest.mkdir(exist_ok=True)
        output_csv = dest / "Nuclei.csv"
        output_csv.write_text("ObjectNumber,Area\n1,42\n")
        output_tiff = dest / "labels.tiff"
        output_tiff.write_bytes(b"II*\x00labels")

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_tiff),
            output_paths=[str(output_csv), str(output_tiff)],
        )

        assert not (dest / "input.tif").exists()
        assert (dest / "Nuclei.csv").read_text() == "ObjectNumber,Area\n1,42\n"
        assert (dest / "labels.tiff").read_bytes() == b"II*\x00labels"
        entities = self._read_entities(dest)
        for eid in (uri(input_tiff), "Nuclei.csv", "labels.tiff"):
            assert entities[eid]["@type"] == "File"
        assert entities["labels.tiff"]["exampleOfWork"] == {"@id": "#output_2"}

    def test_encoding_format(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """Files give their media type and EDAM format, folders their EDAM format; formats are WebPage entities."""
        input_zarr, _ = ome_zarr_dirs
        dest = tmp_path / "crate"
        output_csv = dest / "Nuclei.csv"
        output_csv.write_text("ObjectNumber,Area\n1,42\n")

        create_ro_crate(str(dest), str(bilayers_config), str(input_zarr), [str(output_csv)])

        entities = self._read_entities(dest)
        csv_format = "http://edamontology.org/format_3752"
        zarr_format = "http://edamontology.org/format_3915"
        assert entities["Nuclei.csv"]["encodingFormat"] == ["text/csv", {"@id": csv_format}]
        assert entities[uri(input_zarr)]["encodingFormat"] == {"@id": zarr_format}
        assert entities[csv_format] == {"@id": csv_format, "@type": "WebPage", "name": "CSV"}
        assert entities[zarr_format] == {"@id": zarr_format, "@type": "WebPage", "name": "Zarr"}
        # The parameter refers to the EDAM format only.
        assert entities["#output"]["encodingFormat"] == {"@id": csv_format}
        # Formats are not given as additionalType, which only gives the data type of parameter values.
        assert not any("additionalType" in entity for entity in entities.values() if "encodingFormat" in entity)

    @pytest.mark.parametrize("name, edam", [
        ("image.ome.tiff", "format_3727"), ("image.OME.TIF", "format_3727"), ("image.tif", "format_3591"),
        ("image.ome.zarr", "format_3915"), ("image.ome.zarr/", "format_3915"), ("labels.png", "format_3603"),
        ("photo.jpeg", "format_3579"), ("data.h5", "format_3590"), ("Nuclei.csv", "format_3752"),
        ("table.tsv", "format_3475"), ("table.xlsx", "format_3620"), ("result.json", "format_3464"),
        ("config.yml", "format_3750"), ("meta.xml", "format_2332"), ("log.txt", "format_2330"),
    ])
    def test_edam_format_from_file_name(self, name, edam):
        assert get_file_format(name)[0] == f"http://edamontology.org/{edam}"

    def test_unknown_format_has_no_edam_type(self):
        assert get_file_format("weights.pt") is None

    def test_multiple_outputs_get_distinct_parameters(self, tmp_path, bilayers_config):
        """Each output dataset gets its own FormalParameter."""
        input_zarr = tmp_path / "input.ome.zarr"
        input_zarr.mkdir()
        dest = tmp_path / "crate"
        outputs = []
        for name in ("a.ome.zarr", "b.ome.zarr"):
            out = dest / name
            out.mkdir(parents=True)
            outputs.append(str(out))

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=outputs,
        )

        entities = self._read_entities(dest)
        output_ids = [ref["@id"] for ref in entities["config.yaml"]["output"]]
        assert output_ids == ["#output", "#output_2"]
        assert entities["a.ome.zarr/"]["exampleOfWork"] == {"@id": "#output"}
        assert entities["b.ome.zarr/"]["exampleOfWork"] == {"@id": "#output_2"}

    def test_run_is_described(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """The schema's parameters are FormalParameters; the run is a CreateAction of the workflow."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"

        create_ro_crate(str(dest), str(bilayers_config), str(input_zarr), [str(output_zarr)])

        entities = self._read_entities(dest)
        assert {"@id": "#parameter-model"} in entities["config.yaml"]["input"]
        assert entities["#parameter-model"] == {
            "@id": "#parameter-model", "@type": "FormalParameter", "name": "model",
            "additionalType": "Text", "valueRequired": True, "defaultValue": "MitoNet_v1_mini",
        }
        run = entities["#run"]
        assert run["@type"] == "CreateAction"
        assert run["instrument"] == {"@id": "config.yaml"}
        assert run["object"] == [{"@id": uri(input_zarr)}]
        assert run["result"] == [{"@id": "output.ome.zarr/"}]
        assert {"@id": "#run"} in entities["./"]["mentions"]
        for profile in ("https://w3id.org/ro/wfrun/process/0.5", "https://w3id.org/ro/wfrun/workflow/0.5"):
            assert {"@id": profile} in entities["./"]["conformsTo"]
            assert entities[profile]["@type"] == "CreativeWork"

    def test_parameter_values_from_a_yaml_file(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """Values in a nested YAML file are PropertyValues of the run; the file is added to the crate."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        values = tmp_path / "parameters.yaml"
        values.write_text("segmentation:\n  model: MitoNet_v1\n  tiling:\n    tile_size: [512, 512]\n")

        with pytest.warns(UserWarning, match="'segmentation.tiling.tile_size' is not a parameter"):
            create_ro_crate(str(dest), str(bilayers_config), str(input_zarr), [str(output_zarr)],
                            parameters=str(values))

        entities = self._read_entities(dest)
        assert entities["#value-model"] == {
            "@id": "#value-model", "@type": "PropertyValue", "name": "model", "value": "MitoNet_v1",
            "exampleOfWork": {"@id": "#parameter-model"},
        }
        unknown = entities["#value-segmentation.tiling.tile_size"]
        assert unknown["value"] == "[512, 512]"
        assert "exampleOfWork" not in unknown
        assert entities["#run"]["object"] == [
            {"@id": uri(input_zarr)}, {"@id": "#value-model"}, {"@id": "#value-segmentation.tiling.tile_size"},
        ]
        # The values file is copied into the crate, and describes the run.
        assert (dest / "parameters.yaml").read_text() == values.read_text()
        assert entities["parameters.yaml"]["about"] == {"@id": "#run"}

    def test_parameter_values_from_a_mapping(self, tmp_path, bilayers_config, ome_zarr_dirs):
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"

        create_ro_crate(str(dest), str(bilayers_config), str(input_zarr), [str(output_zarr)],
                        parameters={"model": "MitoNet_v1"})

        entities = self._read_entities(dest)
        assert entities["#value-model"]["value"] == "MitoNet_v1"
        assert {"@id": "#value-model"} in entities["#run"]["object"]
        assert not any(eid.endswith((".yaml", ".json")) and eid not in ("config.yaml", "ro-crate-metadata.json") for eid in entities)

    @staticmethod
    def _read_entities(dest: Path) -> dict:
        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        return {entity["@id"]: entity for entity in metadata["@graph"]}

    @staticmethod
    def _read_ids(dest: Path) -> set[str]:
        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        return {entity["@id"] for entity in metadata["@graph"]}


class TestPreview:
    def test_preview_is_written_and_not_part_of_the_payload(self, tmp_path):
        dest = self._make_crate(tmp_path, make_ome_zarr_v2(tmp_path / "input.ome.zarr"))

        assert (dest / "ro-crate-preview.html").exists()
        entities = TestCreateRoCrate._read_entities(dest)
        assert entities["ro-crate-preview.html"]["about"] == {"@id": "./"}
        assert {"@id": "ro-crate-preview.html"} not in entities["./"]["hasPart"]

    def test_no_preview_when_disabled(self, tmp_path):
        input_zarr = make_ome_zarr_v2(tmp_path / "input.ome.zarr")
        dest = tmp_path / "crate"

        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(input_zarr), gen_preview=False)

        assert not (dest / "ro-crate-preview.html").exists()
        assert "ro-crate-preview.html" not in TestCreateRoCrate._read_ids(dest)

    def test_preview_links_entities_and_terms(self, tmp_path):
        """Every entity has a section, references link to them, and terms link to their definition."""
        dest = self._make_crate(tmp_path, make_ome_zarr_v2(tmp_path / "input.ome.zarr"))
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

        # The metadata and preview files themselves are linked, not described.
        assert '<a href="ro-crate-metadata.json">' in page
        for entity_id in TestCreateRoCrate._read_ids(dest) - {"ro-crate-metadata.json", "ro-crate-preview.html"}:
            assert f"<code>{entity_id}</code>" in page, f"entity '{entity_id}' missing from the preview"
        # The workflow's output links to its FormalParameter's section.
        assert '<a href="#output">output</a>' in page
        assert '<section class="entity" id="output">' in page
        assert '<a href="https://doi.org/10.5281/zenodo.17652333">' in page
        assert '<a href="http://schema.org/exampleOfWork" title="A creative work that this work is an example' in page
        assert '<a href="output.ome.zarr/">open</a>' in page

    def test_preview_shows_csv_and_ome_zarr_details(self, tmp_path):
        input_zarr = make_ome_zarr_v2(tmp_path / "input.ome.zarr")
        dest = tmp_path / "crate"
        dest.mkdir()
        table = dest / "Nuclei.csv"
        table.write_text("ImageNumber,ObjectNumber,AreaShape_Area\n1,1,42.5\n1,2,40.0\n")

        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(input_zarr), [str(table)])
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

        assert "2 rows &times; 3 columns" in page
        assert "<li>AreaShape_Area</li>" in page
        assert "OME-Zarr 0.4" in page
        assert "Axes: c, y (micrometer), x (micrometer)" in page
        assert ("<td>2 &times; 512 &times; 512</td><td>1 &times; 256 &times; 256</td>"
                "<td>&lt;u2</td><td>1 &times; 0.5 &times; 0.5</td>") in page
        assert '<span class="swatch" style="background:#0000FF"></span>DAPI' in page
        assert "Label images: nuclei" in page

    def test_text_files_get_a_browsable_view(self, tmp_path):
        """CSV and other text files link to an HTML view in ro-crate-preview_files/; binary files do not."""
        input_tiff = tmp_path / "input.tif"
        input_tiff.write_bytes(b"II*\x00\x00\x01binary")
        dest = tmp_path / "crate"
        dest.mkdir()
        table = dest / "Nuclei.csv"
        table.write_text("# header l,d\nObjectNumber,AreaShape_Area\n1,42.5\n2,<40>\n")

        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(input_tiff), [str(table)])
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

        assert '<a href="ro-crate-preview_files/Nuclei.csv.html">view</a>' in page
        assert '<a href="Nuclei.csv">raw file</a>' in page
        assert '<a href="ro-crate-preview_files/config.yaml.html">view</a>' in page
        # The referenced input links to where it is.
        assert f'<a href="{uri(input_tiff)}">open</a>' in page
        assert not any("input.tif" in view.name for view in (dest / "ro-crate-preview_files").iterdir())

        table_view = (dest / "ro-crate-preview_files" / "Nuclei.csv.html").read_text(encoding="utf-8")
        assert '<a href="../ro-crate-preview.html#Nuclei.csv">' in table_view
        assert '<a href="../Nuclei.csv">raw file</a>' in table_view
        assert "<th>ObjectNumber</th><th>AreaShape_Area</th>" in table_view
        assert '<tr class="types"><th>integer</th><th>decimal</th></tr>' in table_view
        assert "<tr><td>2</td><td>&lt;40&gt;</td></tr>" in table_view

        config_view = (dest / "ro-crate-preview_files" / "config.yaml.html").read_text(encoding="utf-8")
        assert '<li><span class="key">algorithm_folder_name</span>: <span class="string">empanada_inference</span></li>' in config_view

        # The views are not payload: they are not described in the metadata.
        assert not any(eid.startswith("ro-crate-preview_files") for eid in TestCreateRoCrate._read_ids(dest))

    def test_preview_shows_bilayers_details(self, tmp_path):
        dest = self._make_crate(tmp_path, make_ome_zarr_v2(tmp_path / "input.ome.zarr"))
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

        assert "<strong>Bilayers workflow</strong>" in page
        assert 'Empanada (<a href="https://doi.org/10.1083/jcb.202208005">doi:10.1083/jcb.202208005</a>)' in page
        assert "Docker image: <code>czii/empanada-napari:latest</code> (linux/amd64)" in page
        assert "Command: <code>python -m empanada.inference</code>" in page
        assert "<tr><td>input_image</td><td>image</td><td>--image</td><td></td></tr>" in page
        assert "<tr><td>model</td><td>string</td><td>--model</td><td>MitoNet_v1_mini</td><td></td></tr>" in page

    def test_preview_shows_parameter_values(self, tmp_path):
        input_zarr = make_ome_zarr_v2(tmp_path / "input.ome.zarr")
        dest = tmp_path / "crate"

        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(input_zarr),
                        parameters={"model": "MitoNet_v1"})
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

        assert "<th>Default</th><th>Value</th><th>Description</th>" in page
        assert "<tr><td>model</td><td>string</td><td>--model</td><td>MitoNet_v1_mini</td><td>MitoNet_v1</td><td></td></tr>" in page
        # The inputs and outputs tables have no values.
        assert "<tr><td>input_image</td><td>image</td><td>--image</td><td></td></tr>" in page

    def test_json_and_yaml_views_are_trees(self, tmp_path):
        """JSON and YAML files are shown as a collapsible tree; files that do not parse as plain text."""
        dest = tmp_path / "crate"
        dest.mkdir()
        measurements = dest / "measurements.json"
        write_json(measurements, {"cells": [{"id": 1, "area": 42.5, "url": "https://example.org/<1>"}],
                                  "valid": True, "note": None, "empty": []})
        broken = dest / "broken.yaml"
        broken.write_text("key: [unclosed\n")

        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(make_ome_zarr_v2(tmp_path / "input.ome.zarr")),
                        [str(measurements), str(broken)])
        page = (dest / "ro-crate-preview.html").read_text(encoding="utf-8")
        view = (dest / "ro-crate-preview_files" / "measurements.json.html").read_text(encoding="utf-8")

        assert '<a href="ro-crate-preview_files/measurements.json.html">view</a>' in page
        assert ('<details open><summary><span class="key">cells</span> <span class="type">1 item</span></summary>'
                '<ul><li><details open><summary><span class="index">0</span> <span class="type">3 items</span>') in view
        assert '<li><span class="key">area</span>: 42.5</li>' in view
        assert ('<li><span class="key">url</span>: <a href="https://example.org/&lt;1&gt;">'
                'https://example.org/&lt;1&gt;</a></li>') in view
        assert '<li><span class="key">valid</span>: <span class="type">true</span></li>' in view
        assert '<li><span class="key">note</span>: <span class="type">null</span></li>' in view
        assert '<li><span class="key">empty</span>: <span class="type">[]</span></li>' in view
        broken_view = (dest / "ro-crate-preview_files" / "broken.yaml.html").read_text(encoding="utf-8")
        assert "<pre>key: [unclosed\n</pre>" in broken_view

    def test_large_table_view_is_truncated(self, tmp_path, monkeypatch):
        monkeypatch.setattr("fair_metadata_integration.preview.MAX_VIEW_ROWS", 2)
        table = tmp_path / "crate" / "Image.csv"
        table.parent.mkdir()
        table.write_text("ImageNumber\n1\n2\n3\n")

        dest = self._make_crate(tmp_path, make_ome_zarr_v2(tmp_path / "input.ome.zarr"), [table])

        view = (dest / "ro-crate-preview_files" / "Image.csv.html").read_text(encoding="utf-8")
        assert "3 rows &times; 1 columns, showing the first 2" in view
        assert "<td>3</td>" not in view

    def test_unreadable_details_do_not_break_the_preview(self, tmp_path):
        broken = tmp_path / "broken.ome.zarr"
        broken.mkdir()
        (broken / ".zattrs").write_text("{not json")

        dest = self._make_crate(tmp_path, broken)

        assert "OME-Zarr" not in (dest / "ro-crate-preview.html").read_text(encoding="utf-8")

    def test_cellprofiler_csv_column_types(self, tmp_path):
        table = tmp_path / "Image.csv"
        table.write_text("# header l,d,s\nImageNumber,Count_Cells,FileName_DNA\n1,12.0,a.tif\n2,8.0,b.tif\n")

        assert table_details(table) == {
            "columns": ["ImageNumber", "Count_Cells", "FileName_DNA"],
            "types": ["integer", "decimal", "text"],
            "rows": 2,
        }

    def test_ome_zarr_v3_details(self, tmp_path):
        details = ome_zarr_details(make_ome_zarr_v3(tmp_path / "image.ome.zarr"))

        assert details["version"] == "0.5"
        image = details["images"][0]
        assert image["name"] == "cells"
        assert [level["shape"] for level in image["levels"]] == [[2, 512, 512], [2, 256, 256]]
        assert image["levels"][0]["chunks"] == [1, 256, 256]
        assert image["levels"][0]["dtype"] == "uint16"
        assert [channel["label"] for channel in image["channels"]] == ["DAPI", "GFP"]

    def test_ome_zarr_plate_and_bioformats2raw_details(self, tmp_path):
        plate = tmp_path / "plate.ome.zarr"
        write_json(plate / ".zattrs", {"plate": {
            "version": "0.4", "name": "screen", "rows": [{"name": "A"}, {"name": "B"}],
            "columns": [{"name": "1"}, {"name": "2"}, {"name": "3"}], "wells": [{"path": "A/1"}, {"path": "B/3"}]}})
        converted = tmp_path / "converted.ome.zarr"
        write_json(converted / ".zattrs", {"bioformats2raw.layout": 3})
        make_ome_zarr_v2(converted / "0")
        make_ome_zarr_v2(converted / "1")

        assert ome_zarr_details(plate)["plate"] == {"name": "screen", "rows": 2, "columns": 3, "wells": 2}
        series = ome_zarr_details(converted)["images"]
        assert [image["name"] for image in series] == ["Series 0", "Series 1"]
        assert series[1]["levels"][1]["shape"] == [2, 256, 256]

    def test_plain_folder_has_no_ome_zarr_details(self, tmp_path):
        (tmp_path / "images").mkdir()
        assert ome_zarr_details(tmp_path / "images") is None

    @staticmethod
    def _make_crate(tmp_path: Path, input_path: Path, output_paths: list[Path] | None = None) -> Path:
        dest = tmp_path / "crate"
        if output_paths is None:
            output = dest / "output.ome.zarr"
            output.mkdir(parents=True, exist_ok=True)
            output_paths = [output]
        create_ro_crate(str(dest), str(make_bilayers_config(tmp_path)), str(input_path), [str(p) for p in output_paths])
        return dest


def make_example_crate(tmp_path: Path) -> Path:
    """Write an example crate to inspect under *tmp_path*, print where it is, and return its folder.

    OME-Zarr input with channels and a label image; OME-Zarr (Zarr v3) and CellProfiler CSV outputs.
    """
    sources = tmp_path / "sources"
    sources.mkdir(parents=True, exist_ok=True)

    dest = tmp_path / "output"
    dest.mkdir(parents=True, exist_ok=True)

    bilayers_config = make_bilayers_config(sources)
    input_zarr = make_ome_zarr_v2(sources / "cells.ome.zarr")
    output_labels = make_ome_zarr_v3(dest / "segmentation.ome.zarr")
    output_csv = dest / "Nuclei.csv"
    output_csv.write_text(
        "# header l,l,d,d,s\n"
        "ImageNumber,ObjectNumber,AreaShape_Area,Intensity_MeanIntensity_DAPI,FileName_DAPI\n"
        "1,1,412.0,0.21,cells.ome.zarr\n"
        "1,2,388.0,0.19,cells.ome.zarr\n"
        "1,3,455.0,0.24,cells.ome.zarr\n"
    )

    create_ro_crate(
        dest_path=str(dest),
        workflow_schema_filename=str(bilayers_config),
        input_path=str(input_zarr),
        output_paths=[str(output_labels), str(output_csv)],
    )

    print(f"\nCrate:    {dest}")
    print(f"Metadata: {dest / 'ro-crate-metadata.json'}")
    print(f"Preview:  {dest / 'ro-crate-preview.html'}")
    return dest


def test_example_crate(tmp_path):
    """Writes the example crate and prints its path; pytest keeps tmp_path of the last 3 runs (see with -s)."""
    dest = make_example_crate(tmp_path)

    assert (dest / "ro-crate-preview.html").exists()


if __name__ == "__main__":
    # Write the example crate to a folder that is kept: python tests/test_metadata_integration.py [folder]
    import sys
    import tempfile

    make_example_crate(Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="fair-metadata-crate-")))
