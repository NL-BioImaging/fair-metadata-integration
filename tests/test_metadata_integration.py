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
    input_zarr.mkdir()
    output_zarr.mkdir()
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

        ids = self._read_ids(dest)
        # rocrate normalises paths to forward-slashes with a trailing '/'.
        relative_output = os.path.relpath(str(output_zarr), str(dest)).replace("\\", "/")
        assert any(relative_output in eid for eid in ids), (
            f"Output zarr '{relative_output}' not found in crate entities: {ids}"
        )
        assert any("config.yaml" in eid for eid in ids), (
            f"Bilayers config.yaml not found in crate entities: {ids}"
        )

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
