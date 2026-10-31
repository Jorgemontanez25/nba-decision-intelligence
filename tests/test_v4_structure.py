from lineup_engine import canonical_ids
import pytest

def test_ids():
    assert canonical_ids('5|3|2|4|1') == [1,2,3,4,5]
    with pytest.raises(ValueError): canonical_ids('1|2|3|4|4')
    with pytest.raises(ValueError): canonical_ids('1|2|3')
