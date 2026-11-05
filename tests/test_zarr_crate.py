"""Tests for crates without a workflow, and for the crate in an OME-Zarr store."""
import json
from pathlib import Path

import pytest

from fair_metadata_integration import create_ro_crate, create_zarr_ro_crate, get_ome_zarr_version
from fair_metadata_integration.provenance import find_metadata_value
from test_metadata_integration import make_bilayers_config, make_ome_zarr_v2, make_ome_zarr_v3, write_json

NGFF_05 = 'https://ngff.openmicroscopy.org/0.5/'
NGFF_04 = 'https://ngff.openmicroscopy.org/0.4/'
ZARR_FORMAT = {'@id': 'http://edamontology.org/format_3915'}
SCHEMA = {'url': 'https://example.org/imaging-model.yaml', 'name': 'Imaging model', 'version': '2.0'}


def read_entities(dest: Path) -> dict:
    metadata = json.loads((dest / 'ro-crate-metadata.json').read_text())
    return {entity['@id']: entity for entity in metadata['@graph']}


def as_list(value):
    return value if isinstance(value, list) else [value]


class TestOmeZarrVersion:
    def test_v3(self, tmp_path):
        assert get_ome_zarr_version(make_ome_zarr_v3(tmp_path / 'a.ome.zarr')) == '0.5'

    def test_v2_from_multiscales(self, tmp_path):
        assert get_ome_zarr_version(make_ome_zarr_v2(tmp_path / 'a.ome.zarr')) == '0.4'

    def test_bioformats2raw_from_series(self, tmp_path):
        store = tmp_path / 'a.ome.zarr'
        write_json(store / '.zattrs', {'bioformats2raw.layout': 3})
        write_json(store / '0' / '.zattrs', {'multiscales': [{'version': '0.4'}]})
        assert get_ome_zarr_version(store) == '0.4'

    def test_not_a_store(self, tmp_path):
        assert get_ome_zarr_version(tmp_path) is None


class TestCrateWithoutWorkflow:
    def test_data_only(self, tmp_path):
        data = tmp_path / 'crate' / 'table.csv'
        data.parent.mkdir()
        data.write_text('a,b\n1,2\n')

        create_ro_crate(tmp_path / 'crate', output_paths=[data], name='Tables', description='Some data')

        entities = read_entities(tmp_path / 'crate')
        root = entities['./']
        assert (root['name'], root['description']) == ('Tables', 'Some data')
        assert 'mainEntity' not in root
        assert '#run' not in entities
        assert {'@id': 'table.csv'} in as_list(root['hasPart'])

    def test_parameters_need_a_workflow(self, tmp_path):
        with pytest.raises(ValueError):
            create_ro_crate(tmp_path / 'crate', parameters={'a': 1})

    def test_ome_zarr_inputs_conform_to_their_version(self, tmp_path):
        store = make_ome_zarr_v3(tmp_path / 'input.ome.zarr')
        dest = tmp_path / 'crate'

        create_ro_crate(dest, make_bilayers_config(tmp_path), [store], gen_preview=False)

        entities = read_entities(dest)
        assert {'@id': NGFF_05} in as_list(entities[store.resolve().as_uri() + '/']['conformsTo'])
        assert entities[NGFF_05]['version'] == '0.5'


class TestCreateZarrRoCrate:
    @pytest.fixture()
    def store(self, tmp_path):
        store = make_ome_zarr_v3(tmp_path / 'cells.ome.zarr')
        (store / 'acquisition-metadata.yaml').write_text('instrument: EM\n')
        return store

    def test_root_is_the_store(self, store):
        create_zarr_ro_crate(store)

        root = read_entities(store)['./']
        assert root['name'] == 'cells'
        assert root['description'] == 'OME-Zarr image'
        assert ZARR_FORMAT in as_list(root['encodingFormat'])
        assert {'@id': NGFF_05} in as_list(root['conformsTo'])
        assert (store / 'ro-crate-preview.html').exists()

    def test_store_is_left_as_it_is(self, store):
        before = {p.relative_to(store): p.read_bytes() for p in store.rglob('*') if p.is_file()}
        create_zarr_ro_crate(store, gen_preview=False)
        after = {p.relative_to(store): p.read_bytes() for p in store.rglob('*') if p.is_file()}
        assert set(after) - set(before) == {Path('ro-crate-metadata.json')}
        assert all(after[path] == content for path, content in before.items())

    def test_metadata_files_are_about_the_store_and_conform_to_their_schema(self, store):
        create_zarr_ro_crate(store, [store / 'acquisition-metadata.yaml'], metadata_conforms_to=SCHEMA)

        entities = read_entities(store)
        metadata_file = entities['acquisition-metadata.yaml']
        assert metadata_file['about'] == {'@id': './'}
        assert metadata_file['conformsTo'] == {'@id': SCHEMA['url']}
        assert entities[SCHEMA['url']]['version'] == '2.0'
        assert {'@id': 'acquisition-metadata.yaml'} in as_list(entities['./']['hasPart'])

    def test_description_mentions_labels_and_can_be_given(self, store):
        (store / 'labels').mkdir()
        create_zarr_ro_crate(store, gen_preview=False)
        assert read_entities(store)['./']['description'] == 'OME-Zarr image with labels'

        create_zarr_ro_crate(store, description='Segmented cells', gen_preview=False)
        assert read_entities(store)['./']['description'] == 'Segmented cells'

    def test_given_version_is_used(self, tmp_path):
        store = tmp_path / 'plain.zarr'
        store.mkdir()
        create_zarr_ro_crate(store, ome_version='0.4', gen_preview=False)
        assert {'@id': NGFF_04} in as_list(read_entities(store)['./']['conformsTo'])

    def test_given_version_differing_from_the_store_warns(self, store):
        with pytest.warns(UserWarning, match='0.5'):
            create_zarr_ro_crate(store, ome_version='0.4', gen_preview=False)
        assert {'@id': NGFF_04} in as_list(read_entities(store)['./']['conformsTo'])

    def test_unknown_version_warns(self, tmp_path):
        store = tmp_path / 'plain.zarr'
        store.mkdir()
        with pytest.warns(UserWarning, match='unknown'):
            create_zarr_ro_crate(store, gen_preview=False)
        assert 'conformsTo' not in read_entities(store)['./']

    def test_store_must_exist(self, tmp_path):
        with pytest.raises(ValueError):
            create_zarr_ro_crate(tmp_path / 'missing.ome.zarr')

    def test_metadata_must_be_in_the_store(self, store, tmp_path):
        outside = tmp_path / 'metadata.yaml'
        outside.write_text('a: 1\n')
        with pytest.raises(ValueError):
            create_zarr_ro_crate(store, [outside])


OME_METADATA = {'Instrument': {'Microscope': {'Manufacturer': 'Zeiss', 'Model': 'Crossbeam', 'SerialNumber': 1234}},
                'Image': {'Name': 'tile', 'AcquisitionDate': '2026-01-02T03:04:05'}}
TIFF_METADATA = {'Make': 'FEI', 'Model': 'Helios', 'DateTime': '2026:01:02 04:00:00'}
SOFTWARE = {'name': 'muvis-align', 'url': 'https://github.com/ccp-volume-em/muvis-align', 'version': '1.2'}


class TestStoreProvenance:
    def test_sources_acquisition_derivation_and_measurements(self, tmp_path):
        store = make_ome_zarr_v3(tmp_path / 'output' / 'fused.ome.zarr')
        source_paths = [tmp_path / 'tile1.tiff', tmp_path / 'tile2.tiff']
        for path in source_paths:
            path.write_bytes(b'II*\x00')

        create_zarr_ro_crate(store, source_paths=source_paths, acquisition_metadata=[OME_METADATA, TIFF_METADATA],
                             derivation={'name': 'Fusion to OME-Zarr', 'software': SOFTWARE,
                                         'end_time': '2026-11-05T16:00:00'},
                             measurements={'ncc': 0.75, 'nmi': {'value': 0.5, 'description': 'Registration nmi'}},
                             gen_preview=False)

        entities = read_entities(store)
        sources = [{'@id': path.resolve().as_uri()} for path in source_paths]
        root = entities['./']
        assert root['isBasedOn'] == sources
        # referenced, not part of the store
        assert not any(source in as_list(root.get('hasPart', [])) for source in sources)
        assert entities[sources[0]['@id']]['@type'] == 'File'
        assert root['mentions'] == [{'@id': '#acquisition'}, {'@id': '#derivation'}]
        assert root['datePublished'] == '2026-11-05T16:00:00'

        acquisition = entities['#acquisition']
        assert acquisition['instrument'] == {'@id': '#instrument-zeiss-crossbeam-1234'}
        assert acquisition['result'] == sources
        # the TIFF DateTime is read as such
        assert (acquisition['startTime'], acquisition['endTime']) == ('2026-01-02T03:04:05', '2026-01-02T04:00:00')
        assert entities['#instrument-zeiss-crossbeam-1234'] == {
            '@id': '#instrument-zeiss-crossbeam-1234', '@type': 'IndividualProduct',
            'manufacturer': 'Zeiss', 'name': 'Crossbeam', 'serialNumber': '1234'}

        derivation = entities['#derivation']
        assert derivation['name'] == 'Fusion to OME-Zarr'
        assert derivation['instrument'] == {'@id': SOFTWARE['url']}
        assert derivation['object'] == sources
        assert derivation['result'] == {'@id': './'}

        assert root['variableMeasured'] == [{'@id': '#measurement-ncc'}, {'@id': '#measurement-nmi'}]
        assert entities['#measurement-ncc'] == {'@id': '#measurement-ncc', '@type': 'PropertyValue',
                                                'name': 'ncc', 'value': 0.75}
        assert entities['#measurement-nmi']['description'] == 'Registration nmi'

    def test_acquisition_without_instrument_or_sources(self, tmp_path):
        store = make_ome_zarr_v3(tmp_path / 'fused.ome.zarr')

        create_zarr_ro_crate(store, acquisition_metadata=[{}], gen_preview=False)

        entities = read_entities(store)
        assert 'instrument' not in entities['#acquisition']
        assert entities['#acquisition']['result'] == {'@id': './'}
        assert not any(entity['@type'] == 'IndividualProduct' for entity in entities.values())
        assert 'isBasedOn' not in entities['./'] and 'variableMeasured' not in entities['./']

    def test_preview_shows_the_provenance(self, tmp_path):
        store = make_ome_zarr_v3(tmp_path / 'fused.ome.zarr')

        create_zarr_ro_crate(store, acquisition_metadata=[OME_METADATA],
                             derivation={'name': 'Fusion to OME-Zarr', 'software': SOFTWARE})

        page = (store / 'ro-crate-preview.html').read_text(encoding='utf-8')
        assert '<a href="#derivation">Fusion to OME-Zarr</a>' in page
        assert '<a href="#instrument-zeiss-crossbeam-1234">Crossbeam</a>' in page


def test_find_metadata_value_prefers_context():
    metadata = {'Detector': {'Model': 'camera'}, 'Microscope': {'Model': 'scope'}}
    assert find_metadata_value(metadata, ['model'], ['microscope', '']) == 'scope'
    assert find_metadata_value(metadata, ['model'], ['instrument']) is None
    assert find_metadata_value(TIFF_METADATA, ['manufacturer', 'make'], ['microscope', '']) == 'FEI'
    # keys differing only in case, spaces or separators
    assert find_metadata_value({'Microscope Info': {'Serial_Number': 7}}, ['serialnumber'], ['microscope']) == 7
