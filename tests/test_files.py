"""Tests for writing YAML and parameter values."""
from pathlib import Path

import pytest
import yaml

from fair_metadata_integration import PARAMETERS_FILE_NAME, plain_value, write_parameters, write_yaml


class TestPlainValue:
    @pytest.mark.parametrize('value', ['text', 3, 0.5, True, None])
    def test_plain_values_are_kept(self, value):
        assert plain_value(value) == value

    def test_a_path_becomes_text(self):
        assert plain_value(Path('out')) == 'out'

    def test_nested_values_keep_their_structure(self):
        assert plain_value({'a': [Path('x'), 1], 'b': {'c': (2, Path('y'))}}) == \
            {'a': ['x', 1], 'b': {'c': [2, 'y']}}


class TestWriteYaml:
    def test_hierarchy_and_order_are_kept(self, tmp_path):
        data = {'3D Inference': {'model_config': 'MitoNet_v1', 'confidence_thr': 0.5},
                'Measure Labels': {'save_dir': 'out'}}
        path = write_yaml(tmp_path / 'run' / 'data.yaml', data)

        text = Path(path).read_text(encoding='utf-8')
        assert yaml.safe_load(text) == data
        assert text.index('model_config') < text.index('confidence_thr') < text.index('Measure Labels')


class TestWriteParameters:
    def test_values_are_written_plain_to_the_default_file(self, tmp_path):
        path = write_parameters(tmp_path, {'Measure Labels': {'save_dir': Path('out')}})

        assert Path(path) == tmp_path / PARAMETERS_FILE_NAME
        assert yaml.safe_load(Path(path).read_text(encoding='utf-8')) == {'Measure Labels': {'save_dir': 'out'}}

    def test_file_name_can_be_given(self, tmp_path):
        assert Path(write_parameters(tmp_path, {'a': 1}, file_name='values.yaml')) == tmp_path / 'values.yaml'

    def test_values_must_be_a_mapping(self, tmp_path):
        with pytest.raises(ValueError):
            write_parameters(tmp_path, [1, 2])
