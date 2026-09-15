import json
import os
from pathlib import Path
import pytest

from fair_metadata_integration.metadata_integration import create_ro_crate


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
    """Create input/output ome-zarr directories under *path* and return them."""
    input_zarr = path / "input.ome.zarr"
    output_zarr = path / "output.ome.zarr"
    # Nested content, so tests can check the whole tree is copied into the crate.
    (input_zarr / "0").mkdir(parents=True)
    (input_zarr / ".zattrs").write_text('{"multiscales": []}')
    (input_zarr / "0" / "0.0.0").write_bytes(b"\x01\x02\x03")
    output_zarr.mkdir()
    (output_zarr / ".zattrs").write_text('{"segmentation": true}')
    return input_zarr, output_zarr


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
        dest.mkdir()

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        assert (dest / "ro-crate-metadata.json").exists()

        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        print("\n--- ro-crate-metadata.json ---")
        print(json.dumps(metadata, indent=2))

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

    def test_workflow_ro_crate_profile(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """The crate declares the Workflow RO-Crate profile correctly."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        dest.mkdir()

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        entities = self._read_entities(dest)

        # The metadata descriptor must declare the profile alongside the base spec.
        conforms_to = {
            ref["@id"] for ref in entities["ro-crate-metadata.json"]["conformsTo"]
        }
        assert "https://w3id.org/workflowhub/workflow-ro-crate/1.0" in conforms_to

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
        assert entities["input.ome.zarr/"]["exampleOfWork"] == {"@id": "#input"}
        assert entities["output.ome.zarr/"]["exampleOfWork"] == {"@id": "#output"}

        # The language must describe bilayers, not CWL.
        lang = entities[workflow["programmingLanguage"]["@id"]]
        assert lang["@type"] == "ComputerLanguage"
        assert "ilayers" in lang["name"]

    def test_payload_files_are_copied_into_crate(self, tmp_path, bilayers_config, ome_zarr_dirs):
        """Every entity in the crate is backed by a file that is actually there."""
        input_zarr, output_zarr = ome_zarr_dirs
        dest = tmp_path / "crate"
        dest.mkdir()

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        assert (dest / "config.yaml").read_text() == BILAYERS_CONFIG
        # The zarr directories are copied whole, nested chunks included.
        assert (dest / "input.ome.zarr" / ".zattrs").exists()
        assert (dest / "input.ome.zarr" / "0" / "0.0.0").read_bytes() == b"\x01\x02\x03"
        assert (dest / "output.ome.zarr" / ".zattrs").exists()

        # No entity may describe a file that is missing from the crate.
        for eid in self._read_ids(dest):
            if eid.startswith("#") or eid.startswith("http") or eid == "./":
                continue
            assert (dest / eid).exists(), f"entity '{eid}' has no file in the crate"

    def test_multiple_outputs_get_distinct_parameters(self, tmp_path, bilayers_config):
        """Each output dataset gets its own FormalParameter."""
        input_zarr = tmp_path / "input.ome.zarr"
        input_zarr.mkdir()
        outputs = []
        for name in ("a.ome.zarr", "b.ome.zarr"):
            out = tmp_path / name
            out.mkdir()
            outputs.append(str(out))
        dest = tmp_path / "crate"
        dest.mkdir()

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

    @staticmethod
    def _read_entities(dest: Path) -> dict:
        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        return {entity["@id"]: entity for entity in metadata["@graph"]}

    @staticmethod
    def _read_ids(dest: Path) -> set[str]:
        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        return {entity["@id"] for entity in metadata["@graph"]}


if __name__ == "__main__":
    import pprint
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        bilayers_config = make_bilayers_config(tmp_path)
        input_zarr, output_zarr = make_ome_zarr_dirs(tmp_path)
        dest = tmp_path / "crate"
        dest.mkdir()

        create_ro_crate(
            dest_path=str(dest),
            workflow_schema_filename=str(bilayers_config),
            input_path=str(input_zarr),
            output_paths=[str(output_zarr)],
        )

        metadata = json.loads((dest / "ro-crate-metadata.json").read_text())
        pprint.pprint(metadata)
