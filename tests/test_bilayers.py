"""Tests for generating a Bilayers config."""
from pathlib import Path

import pytest
import yaml

from fair_metadata_integration import (bilayers_config, bilayers_format, create_ro_crate, display_entry,
                                       image_entry, parameter_entry, write_bilayers_config)
from fair_metadata_integration.bilayers import unknown_value_names


def make_config():
    return bilayers_config(
        'empanada_3d',
        {'model_config': 'MitoNet_v1', 'confidence_thr': 0.5, 'downsampling': 1, 'fine_boundaries': False,
         'save_dir': Path('out'), 'unset': None},
        inputs=[image_entry('input_image', 'Input image', 'Image to segment', subtype=['grayscale'],
                            formats=['tiff'], section='inputs', depth=True)],
        outputs=[image_entry('segmentation', formats=['omezarr'], unique_string=['.ome.zarr'],
                             section='outputs', depth=True, pyramidal=True)],
        citations=[{'name': 'empanada-napari', 'doi': '10.1083/jcb.202208005'}],
        docker_image={'org': 'ghcr.io/nl-bioimaging', 'name': 'empanada', 'tag': '1.0', 'platform': 'linux/amd64'},
        cli_command='python run_fair.py',
        choices={'model_config': ['MitoNet_v1', 'MitoNet_v1_mini']},
    )


def by_name(config):
    return {param['name']: param for param in config['parameters']}


class TestBilayersConfig:
    def test_structure(self):
        config = make_config()
        assert config['algorithm_folder_name'] == 'empanada_3d'
        assert config['exec_function']['cli_command'] == 'python run_fair.py'
        assert config['docker_image']['tag'] == '1.0'
        assert [entry['name'] for entry in config['inputs']] == ['input_image']
        assert [entry['name'] for entry in config['outputs']] == ['segmentation']

    def test_unset_values_are_left_out(self):
        assert 'unset' not in by_name(make_config())

    def test_types_follow_the_values(self):
        types = {name: param['type'] for name, param in by_name(make_config()).items()}
        assert types == {'model_config': 'dropdown', 'confidence_thr': 'float', 'downsampling': 'integer',
                         'fine_boundaries': 'checkbox', 'save_dir': 'textbox'}

    def test_values_are_the_defaults(self):
        params = by_name(make_config())
        assert params['confidence_thr']['default'] == 0.5
        assert params['save_dir']['default'] == 'out'
        assert [option['value'] for option in params['model_config']['options']] == ['MitoNet_v1', 'MitoNet_v1_mini']

    def test_image_entry_label_defaults_to_name(self):
        assert image_entry('input_image')['label'] == 'Input image'

    def test_parameter_entry(self):
        entry = parameter_entry('tile_size', 512)
        assert (entry['type'], entry['default'], entry['cli_tag']) == ('integer', 512, '--tile_size')
        assert 'section_id' not in entry

    def test_sections_hold_the_run_values(self):
        config = bilayers_config('segment', {'threshold': 0.5}, section='inference',
                                 display_only=[display_entry('save_dir', 'out', section='measure')])
        assert by_name(config)['threshold']['section_id'] == 'inference'
        display = config['display_only'][0]
        assert (display['name'], display['section_id'], display['default']) == ('save_dir', 'measure', 'out')
        assert 'cli_tag' not in display
        values = {'inference': {'threshold': 0.7}, 'measure': {'save_dir': 'out'}}
        assert unknown_value_names(config, values) == []
        assert unknown_value_names(config, {'threshold': 0.7}) == ['threshold']

    def test_biomero_schema_accepts_config(self):
        adapters = pytest.importorskip('biomero_schema.adapters')
        adapters.parse_descriptor(make_config())


class TestBilayersFormat:
    @pytest.mark.parametrize('path, expected', [
        ('a.tif', 'tiff'), ('a.TIFF', 'tiff'), ('a.ome.zarr', 'omezarr'), ('a.ome.zarr/', 'omezarr'),
        ('a.png', 'png'), ('a.jpg', 'jpeg'),
    ])
    def test_format(self, path, expected):
        assert bilayers_format(path) == expected


class TestWriteBilayersConfig:
    def test_written_config_reads_back_and_makes_a_crate(self, tmp_path):
        config = make_config()
        path = write_bilayers_config(tmp_path / 'crate' / 'config.yaml', config)
        assert yaml.safe_load(Path(path).read_text(encoding='utf-8')) == config

        create_ro_crate(tmp_path / 'crate', path, gen_preview=False)
        assert (tmp_path / 'crate' / 'ro-crate-metadata.json').exists()
