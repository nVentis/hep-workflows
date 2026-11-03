import pytest

from hep_workflows.utils.filenames import splitext_mod

@pytest.mark.parametrize('path, expected', [
    ('sample.slcio', ('sample', '.slcio')),
    ('sample.0-3-5.slcio', ('sample.0-3-5', '.slcio')),
    ('sample.edm4hep.root', ('sample', '.edm4hep.root')),
    ('/data/dir.edm4hep.root/sample.0-1-2.edm4hep.root', ('/data/dir.edm4hep.root/sample.0-1-2', '.edm4hep.root')),
    # other root files and files only containing edm4hep in their name are no edm4hep files
    ('AIDA.root', ('AIDA', '.root')),
    ('edm4hep.root', ('edm4hep', '.root')),
    ('sample.edm4hep', ('sample', '.edm4hep')),
    ('sample.edm4hep.txt', ('sample.edm4hep', '.txt')),
    ('no_extension', ('no_extension', '')),
])
def test_splitext_mod(path, expected):
    assert splitext_mod(path) == expected

def test_splitext_mod_roundtrip():
    for path in ['a.slcio', 'a.b.edm4hep.root', 'a.root', 'a']:
        assert ''.join(splitext_mod(path)) == path
