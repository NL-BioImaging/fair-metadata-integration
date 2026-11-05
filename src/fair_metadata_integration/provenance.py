"""Where data came from: the software that made it, the acquisition of its sources, and values measured on it."""
from collections.abc import Mapping
from datetime import datetime
import re
from urllib.parse import quote

from rocrate.model import ContextEntity

from .files import plain_value

# Sections of acquisition metadata naming the instrument, preferred in this order
INSTRUMENT_CONTEXTS = ['instrument', 'microscope', 'device', 'system', '']
DATETIME_LABELS = ['acquisitiondate', 'datetimeoriginal', 'datetime']


def add_software(crate, software):
    """The SoftwareApplication described by the mapping *software*: its 'name', and optionally 'url' and 'version'."""
    if not isinstance(software, Mapping) or not software.get('name'):
        raise ValueError("Software needs a 'name'")
    properties = {'@type': 'SoftwareApplication', 'name': str(software['name'])}
    if software.get('url'):
        properties['url'] = str(software['url'])
    if software.get('version'):
        properties['softwareVersion'] = str(software['version'])
    identifier = software.get('url') or f'#software-{quote(str(software["name"]))}'
    return crate.add(ContextEntity(crate, str(identifier), properties))


def add_action_times(action, start_time=None, end_time=None):
    """Give the *action* entity its start and end time, where known."""
    for key, value in (('startTime', start_time), ('endTime', end_time)):
        if value:
            action[key] = to_iso_datetime(value)


def add_derivation(crate, derivation, source_entities, result):
    """The CreateAction that made *result* from *source_entities*, described by the mapping *derivation*:
    its 'name', and optionally its 'software' (see add_software), 'start_time' and 'end_time'."""
    if not isinstance(derivation, Mapping) or not derivation.get('name'):
        raise ValueError("A derivation needs a 'name'")
    action = crate.add(ContextEntity(crate, '#derivation', {'@type': 'CreateAction', 'name': str(derivation['name'])}))
    if derivation.get('software'):
        action['instrument'] = add_software(crate, derivation['software'])
    if source_entities:
        action['object'] = source_entities
    action['result'] = result
    add_action_times(action, derivation.get('start_time'), derivation.get('end_time'))
    crate.root_dataset.append_to('mentions', action)
    return action


def add_measurements(crate, measurements, entity):
    """PropertyValues of *entity*'s variableMeasured, from the mapping of names to a value, or to a mapping of
    its 'value' and optionally 'description' and 'unit'."""
    for name, measurement in measurements.items():
        if not isinstance(measurement, Mapping):
            measurement = {'value': measurement}
        properties = {'@type': 'PropertyValue', 'name': str(name), 'value': plain_value(measurement.get('value'))}
        if measurement.get('description'):
            properties['description'] = str(measurement['description'])
        if measurement.get('unit'):
            properties['unitText'] = str(measurement['unit'])
        entity.append_to('variableMeasured', crate.add(ContextEntity(crate, f'#measurement-{quote(str(name))}',
                                                                     properties)))


def add_acquisition(crate, metadatas, result):
    """The CreateAction that acquired *result*, with the instrument and times found in the source *metadatas*."""
    action = crate.add(ContextEntity(crate, '#acquisition', {'@type': 'CreateAction', 'name': 'Image acquisition'}))
    instrument = next((found for found in map(find_instrument, metadatas) if found), None)
    if instrument:
        action['instrument'] = add_instrument(crate, instrument)
    action['result'] = result
    times = sorted(time for time in (to_iso_datetime(find_metadata_value(metadata, DATETIME_LABELS))
                                     for metadata in metadatas) if time)
    if times:
        add_action_times(action, times[0], times[-1])
    crate.root_dataset.append_to('mentions', action)
    return action


def find_instrument(metadata):
    """The instrument's properties named in the *metadata*, by what names it."""
    properties = {}
    for key, labels in (('manufacturer', ['manufacturer', 'make']), ('name', ['model']),
                        ('serialNumber', ['serialnumber', 'serial'])):
        value = find_metadata_value(metadata, labels, INSTRUMENT_CONTEXTS)
        if value:
            # schema.org serialNumber is text
            properties[key] = str(value)
    return properties


def add_instrument(crate, properties):
    # the same instrument gets the same id in every crate
    label = re.sub(r'[^a-z0-9]+', '-', ' '.join(properties.values()).lower()).strip('-')
    return crate.add(ContextEntity(crate, f'#instrument-{label}', {'@type': 'IndividualProduct', **properties}))


def to_iso_datetime(value):
    if not value:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    text = str(value)
    try:
        # TIFF's DateTime tag
        return datetime.strptime(text, '%Y:%m:%d %H:%M:%S').isoformat()
    except ValueError:
        return text


def find_metadata_value(metadata, labels, contexts=('',)):
    """The first field named one of the labels, preferring each context in turn: a dict key on its path."""
    for context in contexts:
        for label in labels:
            value = find_field(metadata, label, context)
            if value is not None:
                return value
    return None


def find_field(metadata, label, context, path=''):
    if isinstance(metadata, list):
        for item in metadata:
            match = find_field(item, label, context, path)
            if match is not None:
                return match
    elif isinstance(metadata, Mapping):
        for key, value in metadata.items():
            if isinstance(value, (Mapping, list)):
                match = find_field(value, label, context, f'{path}/{normalise_key(key)}')
                if match is not None:
                    return match
            elif normalise_key(key) == label and context in path and value not in (None, ''):
                return value
    return None


def normalise_key(key):
    # Serial Number, serial_number and SerialNumber name the same field
    return re.sub(r'[^a-z0-9]', '', str(key).lower())
