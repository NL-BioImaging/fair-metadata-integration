"""The licenses a crate's content can be given: the common ones for data, by URL."""

COMMON_LICENSES = [
    {'url': 'https://creativecommons.org/licenses/by/4.0/', 'name': 'CC BY 4.0',
     'description': 'Creative Commons Attribution 4.0 International'},
    {'url': 'https://creativecommons.org/licenses/by-sa/4.0/', 'name': 'CC BY-SA 4.0',
     'description': 'Creative Commons Attribution-ShareAlike 4.0 International'},
    {'url': 'https://creativecommons.org/licenses/by-nc/4.0/', 'name': 'CC BY-NC 4.0',
     'description': 'Creative Commons Attribution-NonCommercial 4.0 International'},
    {'url': 'https://creativecommons.org/licenses/by-nc-sa/4.0/', 'name': 'CC BY-NC-SA 4.0',
     'description': 'Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International'},
    {'url': 'https://creativecommons.org/licenses/by-nd/4.0/', 'name': 'CC BY-ND 4.0',
     'description': 'Creative Commons Attribution-NoDerivatives 4.0 International'},
    {'url': 'https://creativecommons.org/licenses/by-nc-nd/4.0/', 'name': 'CC BY-NC-ND 4.0',
     'description': 'Creative Commons Attribution-NonCommercial-NoDerivatives 4.0 International'},
    {'url': 'https://creativecommons.org/publicdomain/zero/1.0/', 'name': 'CC0 1.0',
     'description': 'Creative Commons Zero 1.0 Universal, public domain dedication'},
    {'url': 'https://opendatacommons.org/licenses/by/1-0/', 'name': 'ODC-By 1.0',
     'description': 'Open Data Commons Attribution License 1.0'},
    {'url': 'https://opendatacommons.org/licenses/odbl/1-0/', 'name': 'ODbL 1.0',
     'description': 'Open Data Commons Open Database License 1.0'},
    {'url': 'https://opendatacommons.org/licenses/pddl/1-0/', 'name': 'PDDL 1.0',
     'description': 'Open Data Commons Public Domain Dedication and License 1.0'},
]
# RO-Crate requires a license on the root; this one applies unless another is given
DEFAULT_LICENSE = COMMON_LICENSES[0]
