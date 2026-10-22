"""Human-readable ro-crate-preview.html: every entity of the crate, cross-linked, with file details."""
import csv
import html
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import url2pathname

import yaml
from rocrate import vocabs
from rocrate.model import Preview

# Supporting files of the preview, as the RO-Crate specification names them
VIEWS_DIR = 'ro-crate-preview_files'
# Limits of the browsable views of text files
MAX_VIEW_ROWS = 1000
MAX_VIEW_BYTES = 1_000_000


class CratePreview(Preview):
    """RO-Crate preview listing every entity with all its properties.

    References to other entities link to their section of the page, external URIs and
    property names link to their definitions, and CSV/TSV files, bilayers configurations and
    OME-Zarr folders get a summary of their content, read from the entity's source. Text files,
    which a browser would download rather than show, get a browsable view in
    ro-crate-preview_files/: a table for CSV/TSV, a tree of keys and values for JSON/YAML.
    """

    def _index(self):
        entities = {e.id: e.as_jsonld() for e in self.crate.get_entities() if e is not self}
        return entities, make_anchors(entities)

    def _views(self, anchors):
        """Map the @id of each data entity with a text file source to (its view's path, its source)."""
        views = {}
        for entity in self.crate.data_entities:
            source = local_source(entity)
            if source is not None and is_text_file(source):
                views[entity.id] = (f'{VIEWS_DIR}/{anchors[entity.id]}.html', Path(source))
        return views

    def generate_views(self):
        """Yield the (path, HTML) of the view of each text file."""
        entities, anchors = self._index()
        for entity_id, (view_path, source) in self._views(anchors).items():
            yield view_path, render_view(entity_id, anchors[entity_id], source)

    def stream(self, chunk_size=8192):
        yield self.id, self.generate_html().encode('utf-8')
        for view_path, page in self.generate_views():
            yield view_path, page.encode('utf-8')

    def write(self, dest_base):
        for path, content in self.stream():
            out_path = Path(dest_base) / path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(content)

    def generate_html(self):
        crate = self.crate
        root = crate.root_dataset
        entities, anchors = self._index()
        views = self._views(anchors)
        terms = crate.metadata.extra_terms

        def section(entity, source=None):
            view = views.get(entity.id, (None,))[0]
            return render_entity(entity.as_jsonld(), entities, anchors, terms, source, view)

        title = html.escape(str(root.get('name') or 'RO-Crate'))
        description = root.get('description')
        parts = [f'<h1>{title}</h1>']
        if description:
            parts.append(f'<p class="description">{html.escape(str(description))}</p>')
        parts.append('<p>Machine-readable metadata: <a href="ro-crate-metadata.json">ro-crate-metadata.json</a></p>')
        parts.append('<h2>Root dataset</h2>' + section(root))
        if crate.data_entities:
            parts.append('<h2>Files and folders</h2>')
            parts.extend(section(e, local_source(e)) for e in crate.data_entities)
        if crate.contextual_entities:
            parts.append('<h2>Contextual entities</h2>')
            parts.extend(section(e) for e in crate.contextual_entities)
        return PAGE.format(title=title, style=STYLE, main_class='', body='\n'.join(parts))


def local_source(entity):
    """The local path an entity was made from, also for data referenced by its file URI; else None."""
    source = getattr(entity, 'source', None)
    if isinstance(source, str) and source.startswith('file:'):
        return Path(url2pathname(urlsplit(source).path))
    return source


def make_anchors(entities):
    """Map each entity @id to a unique, readable HTML id."""
    anchors, used = {}, set()
    for entity_id in entities:
        base = re.sub(r'[^A-Za-z0-9._-]+', '-', entity_id).strip('-.') or 'root'
        anchor, n = base, 2
        while anchor in used:
            anchor, n = f'{base}-{n}', n + 1
        used.add(anchor)
        anchors[entity_id] = anchor
    return anchors


def term_uri(term, extra_terms):
    """The URI a property or type name resolves to in the crate's context, or None."""
    value = extra_terms.get(term)
    if isinstance(value, dict):
        value = value.get('@id') or value.get('@reverse')
    if value:
        return value
    try:
        return vocabs.term_to_uri(term)
    except KeyError:
        return None


def term_doc(uri):
    comment = vocabs.SCHEMA_MAP.get(re.sub(r'^https?://schema.org/', 'schema:', uri or ''), {}).get('rdfs:comment', '')
    # Plain text: drop schema.org's [[Term]] and Markdown [text](url) link markup
    comment = re.sub(r'\[\[([^]]*)]]', r'\1', comment if isinstance(comment, str) else '')
    return re.sub(r'\[([^]]*)]\([^)]*\)', r'\1', comment)


def render_term(term, extra_terms):
    uri = term_uri(term, extra_terms)
    if not uri:
        return html.escape(term)
    doc = term_doc(uri)
    title = f' title="{html.escape(doc)}"' if doc else ''
    return f'<a href="{html.escape(uri)}"{title}>{html.escape(term)}</a>'


def render_value(value, entities, anchors):
    if isinstance(value, list):
        if len(value) == 1:
            return render_value(value[0], entities, anchors)
        return '<ul>' + ''.join(f'<li>{render_value(v, entities, anchors)}</li>' for v in value) + '</ul>'
    if isinstance(value, dict):
        if '@id' in value:
            ref = value['@id']
            if ref in entities:
                label = entities[ref].get('name') or ref
                return f'<a href="#{anchors[ref]}">{html.escape(str(label))}</a>'
            return render_value(ref, entities, anchors)
        if '@value' in value:
            return html.escape(str(value['@value']))
        return f'<code>{html.escape(json.dumps(value))}</code>'
    text = str(value)
    if re.match(r'^(https?|ftp)://', text):
        return f'<a href="{html.escape(text)}">{html.escape(text)}</a>'
    return html.escape(text)


def render_entity(entity, entities, anchors, extra_terms, source=None, view=None):
    entity_id = entity['@id']
    types = entity.get('@type', [])
    types = types if isinstance(types, list) else [types]
    meta = [f'<code>{html.escape(entity_id)}</code>']
    if re.match(r'^(https?|ftp)://', entity_id):
        meta = [f'<a href="{html.escape(entity_id)}">{meta[0]}</a>']
    if types:
        meta.append(', '.join(render_term(t, extra_terms) for t in types))
    if view:
        meta.append(f'<a href="{html.escape(quote(view))}">view</a>')
        meta.append(f'<a href="{html.escape(file_href(entity_id))}">raw file</a>')
    elif source is not None:
        meta.append(f'<a href="{html.escape(file_href(entity_id))}">open</a>')
    rows = ''.join(
        f'<dt>{render_term(key, extra_terms)}</dt><dd>{render_value(value, entities, anchors)}</dd>'
        for key, value in entity.items() if key not in ('@id', '@type')
    )
    details = render_details(source) if source is not None else ''
    return (f'<section class="entity" id="{anchors[entity_id]}">'
            f'<h3>{html.escape(str(entity.get("name") or entity_id))}</h3>'
            f'<p class="meta">{" &middot; ".join(meta)}</p>{details}<dl>{rows}</dl></section>')


def render_details(source):
    """Content summary for a CSV/TSV file, a bilayers configuration or an OME-Zarr folder; empty if there is none."""
    try:
        path = Path(source)
        if path.is_file() and path.suffix.lower() in ('.csv', '.tsv'):
            return render_table_details(table_details(path))
        if path.is_file() and path.suffix.lower() in STRUCTURED_SUFFIXES:
            details = bilayers_details(read_structured(path))
            if details:
                return render_bilayers_details(details)
        if path.is_dir():
            details = ome_zarr_details(path)
            if details:
                return render_ome_zarr_details(details)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, csv.Error, yaml.YAMLError):
        pass
    return ''


# File name endings of the structured (JSON/YAML) text files that get a tree view
STRUCTURED_SUFFIXES = ('.json', '.yaml', '.yml')


def read_structured(path):
    """The parsed content of a JSON or YAML file."""
    with open(path, encoding='utf-8') as f:
        return json.load(f) if Path(path).suffix.lower() == '.json' else yaml.safe_load(f)


def bilayers_details(config):
    """Summary of a bilayers workflow configuration, or None if *config* is not one."""
    if not isinstance(config, dict) or not {'docker_image', 'exec_function'} <= config.keys():
        return None

    def items(key):
        return [item for item in config.get(key) or [] if isinstance(item, dict)]

    image = config.get('docker_image') or {}
    docker_image = '/'.join(str(image[k]) for k in ('org', 'name') if image.get(k))
    if docker_image and image.get('tag'):
        docker_image += f':{image["tag"]}'
    return {
        'citations': items('citations'),
        'docker_image': docker_image,
        'platform': image.get('platform'),
        'command': (config.get('exec_function') or {}).get('cli_command'),
        'inputs': items('inputs'),
        'outputs': items('outputs'),
        'parameters': items('parameters'),
    }


def render_bilayers_details(details):
    parts = ['<p><strong>Bilayers workflow</strong></p>']
    for citation in details['citations']:
        text = html.escape(str(citation.get('name') or ''))
        doi = citation.get('doi')
        if doi:
            url = html.escape(f'https://doi.org/{quote(str(doi))}')
            text += f' (<a href="{url}">doi:{html.escape(str(doi))}</a>)'
        if citation.get('description'):
            text += f': {html.escape(str(citation["description"]))}'
        parts.append(f'<p>{text}</p>')
    if details['docker_image']:
        platform = f' ({html.escape(str(details["platform"]))})' if details.get('platform') else ''
        parts.append(f'<p>Docker image: <code>{html.escape(details["docker_image"])}</code>{platform}</p>')
    if details['command']:
        parts.append(f'<p>Command: <code>{html.escape(str(details["command"]))}</code></p>')
    for key, title in (('inputs', 'Inputs'), ('outputs', 'Outputs'), ('parameters', 'Parameters')):
        if details[key]:
            parts.append(f'<p>{title}:</p>' + render_bilayers_items(details[key], with_default=key == 'parameters'))
    return '<div class="details">' + ''.join(parts) + '</div>'


def render_bilayers_items(items, with_default=False):
    """Table of the inputs, outputs or parameters of a bilayers configuration."""
    columns = ['Name', 'Type', 'Option'] + (['Default'] if with_default else []) + ['Description']
    head = '<tr>' + ''.join(f'<th>{c}</th>' for c in columns) + '</tr>'

    def cell(value):
        return f'<td>{html.escape("" if value is None else str(value))}</td>'

    rows = ''.join(
        '<tr>' + cell(item.get('name')) + cell(item.get('type')) + cell(item.get('cli_tag'))
        + (cell(item.get('default')) if with_default else '')
        + cell(item.get('description') or item.get('label')) + '</tr>'
        for item in items
    )
    return f'<table>{head}{rows}</table>'


# Column type codes of CellProfiler's "# header" line
COLUMN_TYPES = {'l': 'integer', 'd': 'decimal', 's': 'text'}


def table_details(path):
    """Column names (and types, if given) and number of data rows of a CSV or TSV file."""
    details = read_table(path)
    del details['data']
    return details


def read_table(path, max_rows=0):
    """Column names, column types, number of data rows and the first *max_rows* rows of a CSV or TSV file.

    Leading comment lines starting with '#' are skipped; a CellProfiler "# header" line
    gives the column types.
    """
    delimiter = '\t' if Path(path).suffix.lower() == '.tsv' else ','
    with open(path, newline='', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f, delimiter=delimiter)
        columns, types = [], []
        for row in reader:
            if row and row[0].startswith('#'):
                if row[0].startswith('# header'):
                    types = [row[0].removeprefix('# header').strip()] + row[1:]
                continue
            columns = row
            break
        data, rows = [], 0
        for row in reader:
            if rows < max_rows:
                data.append(row)
            rows += 1
    if len(types) != len(columns):
        types = []
    return {'columns': columns, 'types': [COLUMN_TYPES.get(t, t) for t in types], 'rows': rows, 'data': data}


def is_absolute_uri(value):
    return re.match(r'^[a-z][a-z0-9+.-]*:', value, re.IGNORECASE) is not None


def file_href(entity_id, base=''):
    """Link to a file or folder in the crate, relative to *base*; absolute URIs are kept as they are."""
    return entity_id if is_absolute_uri(entity_id) else base + quote(entity_id)


def is_text_file(source):
    """Whether *source* is a local file of (UTF-8) text, judged by its first 8 KB."""
    try:
        path = Path(source)
        if not path.is_file():
            return False
        with open(path, 'rb') as f:
            head = f.read(8192)
    except (OSError, TypeError, ValueError):
        return False
    if b'\0' in head:
        return False
    try:
        head.decode('utf-8')
    except UnicodeDecodeError as error:
        # A multi-byte character cut off at the end of the sample is fine
        return error.start >= len(head) - 3
    return True


def render_view(entity_id, anchor, source):
    """Browsable HTML of a text file: a table for CSV/TSV, a tree for JSON/YAML, the text itself otherwise."""
    name = html.escape(entity_id)
    back = f'../ro-crate-preview.html#{quote(anchor)}'
    raw = file_href(entity_id, '../')
    parts = [f'<p class="nav"><a href="{html.escape(back)}">&larr; Back to the crate</a> &middot; '
             f'<a href="{html.escape(raw)}">raw file</a></p>', f'<h1>{name}</h1>']
    try:
        if source.suffix.lower() in ('.csv', '.tsv'):
            parts.append(render_table_view(read_table(source, MAX_VIEW_ROWS)))
        elif source.suffix.lower() in STRUCTURED_SUFFIXES and (tree := render_structured_view(source)):
            parts.append(tree)
        else:
            with open(source, encoding='utf-8', errors='replace') as f:
                text = f.read(MAX_VIEW_BYTES + 1)
            if len(text) > MAX_VIEW_BYTES:
                parts.append(f'<p class="note">Showing the first {MAX_VIEW_BYTES:,} characters.</p>')
            parts.append(f'<pre>{html.escape(text[:MAX_VIEW_BYTES])}</pre>')
    except (OSError, ValueError, csv.Error) as error:
        parts.append(f'<p class="note">The file could not be read: {html.escape(str(error))}</p>')
    return PAGE.format(title=name, style=STYLE, main_class='wide', body='\n'.join(parts))


def render_structured_view(source):
    """Collapsible tree of the content of a JSON or YAML file; None if it is too large or cannot be parsed."""
    try:
        if source.stat().st_size > MAX_VIEW_BYTES:
            return None
        content = read_structured(source)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(content, (dict, list)):
        return None
    return f'<div class="tree">{render_tree(content)}</div>'


def render_tree(value):
    """Nested lists of the keys and values of parsed JSON/YAML; non-empty mappings and lists can be collapsed."""
    if isinstance(value, dict):
        entries = [(f'<span class="key">{html.escape(str(key))}</span>', item) for key, item in value.items()]
    elif isinstance(value, list):
        entries = [(f'<span class="index">{i}</span>', item) for i, item in enumerate(value)]
    else:
        return render_scalar(value)
    if not entries:
        return f'<span class="type">{"{}" if isinstance(value, dict) else "[]"}</span>'
    lines = []
    for key, item in entries:
        if isinstance(item, (dict, list)) and item:
            size = f'{len(item)} {"item" if len(item) == 1 else "items"}'
            lines.append(f'<li><details open><summary>{key} '
                         f'<span class="type">{size}</span></summary>{render_tree(item)}</details></li>')
        else:
            lines.append(f'<li>{key}: {render_tree(item)}</li>')
    return '<ul>' + ''.join(lines) + '</ul>'


def render_scalar(value):
    if value is None:
        return '<span class="type">null</span>'
    if isinstance(value, bool):
        return f'<span class="type">{str(value).lower()}</span>'
    text = html.escape(str(value))
    if isinstance(value, (int, float)):
        return text
    if re.match(r'^(https?|ftp)://', str(value)):
        return f'<a href="{text}">{text}</a>'
    return f'<span class="string">{text}</span>'


def render_table_view(table):
    columns, types, data = table['columns'], table['types'], table['data']
    head = '<tr>' + ''.join(f'<th>{html.escape(c)}</th>' for c in columns) + '</tr>'
    if types:
        head += '<tr class="types">' + ''.join(f'<th>{html.escape(t)}</th>' for t in types) + '</tr>'
    body = ''.join('<tr>' + ''.join(f'<td>{html.escape(v)}</td>' for v in row) + '</tr>' for row in data)
    shown = f', showing the first {len(data):,}' if len(data) < table['rows'] else ''
    return (f'<p>{table["rows"]:,} rows &times; {len(columns):,} columns{shown}</p>'
            f'<div class="table-view"><table><thead>{head}</thead><tbody>{body}</tbody></table></div>')


def render_table_details(details):
    columns = details['columns']
    types = details['types'] or [''] * len(columns)
    names = ''.join(f'<li>{html.escape(c)}' + (f' <span class="type">{html.escape(t)}</span>' if t else '') + '</li>'
                    for c, t in zip(columns, types))
    return (f'<div class="details"><p><strong>Table:</strong> {details["rows"]} rows &times; {len(columns)} columns</p>'
            f'<details><summary>Columns</summary><ol class="columns">{names}</ol></details></div>')


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def zarr_attributes(path):
    """OME attributes of a Zarr group, for Zarr v3 (OME-Zarr 0.5) and v2 (up to 0.4)."""
    group = read_json(path / 'zarr.json')
    if isinstance(group, dict):
        attributes = group.get('attributes', {})
        return attributes.get('ome', attributes)
    attributes = read_json(path / '.zattrs')
    return attributes if isinstance(attributes, dict) else None


def zarr_array(path):
    """Shape, chunks and data type of a Zarr v3 or v2 array."""
    array = read_json(path / 'zarr.json')
    if isinstance(array, dict) and array.get('node_type') == 'array':
        chunks = array.get('chunk_grid', {}).get('configuration', {}).get('chunk_shape')
        return {'shape': array.get('shape'), 'chunks': chunks, 'dtype': array.get('data_type')}
    array = read_json(path / '.zarray')
    if isinstance(array, dict):
        return {'shape': array.get('shape'), 'chunks': array.get('chunks'), 'dtype': array.get('dtype')}
    return None


def ome_zarr_details(path):
    """Summary of an OME-Zarr folder: its images, label images and plate layout, or None if it is not one."""
    attributes = zarr_attributes(path)
    if not attributes:
        return None
    details = {'version': attributes.get('version')}
    if 'multiscales' in attributes:
        details['images'] = [image_details(path, attributes)]
    elif 'bioformats2raw.layout' in attributes:
        # Each numbered subgroup is an image series
        series = sorted((p for p in path.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))
        details['images'] = [image_details(p, zarr_attributes(p) or {}, name=f'Series {p.name}') for p in series]
    if 'plate' in attributes:
        plate = attributes['plate']
        details['plate'] = {
            'name': plate.get('name'),
            'rows': len(plate.get('rows', [])),
            'columns': len(plate.get('columns', [])),
            'wells': len(plate.get('wells', [])),
        }
    labels = zarr_attributes(path / 'labels') if (path / 'labels').is_dir() else None
    if labels and labels.get('labels'):
        details['labels'] = labels['labels']
    if not details.get('images') and 'plate' not in details:
        return None
    if not details['version']:
        multiscales = (details.get('images') or [{}])[0]
        details['version'] = multiscales.get('version')
    return details


def image_details(path, attributes, name=None):
    multiscales = attributes.get('multiscales', [{}])[0]
    axes = [axis if isinstance(axis, str) else axis.get('name', '') + (f' ({axis["unit"]})' if axis.get('unit') else '')
            for axis in multiscales.get('axes', [])]
    levels = []
    for dataset in multiscales.get('datasets', []):
        array = zarr_array(path / dataset['path']) or {}
        scale = next((t.get('scale') for t in dataset.get('coordinateTransformations', [])
                      if t.get('type') == 'scale'), None)
        levels.append({'path': dataset['path'], 'scale': scale, **array})
    channels = [{'label': c.get('label', ''), 'color': c.get('color')}
                for c in attributes.get('omero', {}).get('channels', [])]
    return {
        'name': name or multiscales.get('name'),
        'version': multiscales.get('version'),
        'axes': axes,
        'levels': levels,
        'channels': channels,
    }


def format_list(values):
    return ' &times; '.join(f'{v:g}' if isinstance(v, float) else html.escape(str(v)) for v in values or [])


def render_ome_zarr_details(details):
    version = f' {html.escape(str(details["version"]))}' if details.get('version') else ''
    parts = [f'<p><strong>OME-Zarr{version}</strong></p>']
    plate = details.get('plate')
    if plate:
        name = f'{html.escape(str(plate["name"]))}: ' if plate.get('name') else ''
        parts.append(f'<p>Plate {name}{plate["rows"]} rows &times; {plate["columns"]} columns, {plate["wells"]} wells</p>')
    for image in details.get('images', []):
        if image.get('name'):
            parts.append(f'<p><strong>{html.escape(str(image["name"]))}</strong></p>')
        if image['axes']:
            parts.append(f'<p>Axes: {html.escape(", ".join(image["axes"]))}</p>')
        if image['levels']:
            rows = ''.join(
                f'<tr><td>{html.escape(str(level["path"]))}</td><td>{format_list(level.get("shape"))}</td>'
                f'<td>{format_list(level.get("chunks"))}</td><td>{html.escape(str(level.get("dtype") or ""))}</td>'
                f'<td>{format_list(level.get("scale"))}</td></tr>'
                for level in image['levels']
            )
            parts.append('<table><tr><th>Level</th><th>Shape</th><th>Chunks</th><th>Type</th><th>Scale</th></tr>'
                         f'{rows}</table>')
        if image['channels']:
            channels = ''.join(
                f'<li><span class="swatch" style="background:#{html.escape(c["color"])}"></span>{html.escape(c["label"])}</li>'
                if c.get('color') and re.fullmatch(r'[0-9A-Fa-f]{6}', c['color']) else f'<li>{html.escape(c["label"])}</li>'
                for c in image['channels']
            )
            parts.append(f'<p>Channels:</p><ul class="channels">{channels}</ul>')
    if details.get('labels'):
        parts.append(f'<p>Label images: {html.escape(", ".join(map(str, details["labels"])))}</p>')
    return '<div class="details">' + ''.join(parts) + '</div>'


STYLE = """\
:root { --fg: #222; --muted: #666; --bg: #f4f4f4; --card: #fff; --line: #ddd; --accent: #2a6f97; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6e6e6; --muted: #a0a0a0; --bg: #161616; --card: #202020; --line: #3a3a3a; --accent: #7fb8db; }
}
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
main.wide { max-width: none; }
a { color: var(--accent); }
h1 { margin-top: 0; overflow-wrap: anywhere; }
h2 { margin-top: 2em; border-bottom: 1px solid var(--line); }
.entity { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 12px 16px; margin: 12px 0; }
.entity:target { outline: 2px solid var(--accent); }
.entity h3 { margin: 0; }
.meta { color: var(--muted); margin: 4px 0 8px; overflow-wrap: anywhere; }
dl { display: grid; grid-template-columns: minmax(8em, max-content) 1fr; gap: 4px 16px; margin: 0; }
dt { font-weight: 600; }
dd { margin: 0; overflow-wrap: anywhere; }
dd ul { margin: 0; padding-left: 1.2em; }
.details { border-left: 3px solid var(--accent); padding: 4px 12px; margin: 8px 0 12px; }
.details p { margin: 4px 0; }
table { border-collapse: collapse; margin: 4px 0; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--line); padding: 2px 8px; text-align: left; }
.columns { columns: 3 14em; margin: 4px 0; overflow-wrap: anywhere; }
.type { color: var(--muted); font-size: 0.85em; }
.channels { list-style: none; padding: 0; margin: 4px 0; }
.swatch { display: inline-block; width: 0.9em; height: 0.9em; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
.nav { margin: 0 0 8px; }
.note { color: var(--muted); }
.tree { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px;
        font: 13px/1.6 ui-monospace, monospace; overflow-x: auto; }
.tree ul { list-style: none; margin: 0; padding-left: 1.4em; }
.tree > ul { padding-left: 0; }
.tree summary { cursor: pointer; }
.tree .key { font-weight: 600; }
.tree .index { color: var(--muted); }
.tree .string { white-space: pre-wrap; overflow-wrap: anywhere; }
pre { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 13px; }
.table-view { overflow: auto; max-height: 80vh; border: 1px solid var(--line); background: var(--card); }
.table-view table { display: table; margin: 0; font-size: 13px; }
.table-view th { position: sticky; top: 0; background: var(--card); white-space: nowrap; }
.table-view tr.types th { top: 1.75em; color: var(--muted); font-weight: normal; }
.table-view td { white-space: nowrap; }
"""

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{style}</style>
</head>
<body>
<main class="{main_class}">
{body}
</main>
</body>
</html>
"""
