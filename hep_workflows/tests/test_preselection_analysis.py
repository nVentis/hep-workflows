import numpy as np
import pytest

from hep_workflows.utils.ProcessIndex import ProcessIndex
from hep_workflows.utils.preselection_analysis import combined_cross_section, get_pol_key, get_w_pol, sample_weight, w_prefacs

def make_processes(cross_sections:dict[str, float])->np.ndarray:
    return np.array([(i, proc_pol[:-3], proc_pol, 0, 0, cross_sec, 0., 0) for i, (proc_pol, cross_sec) in enumerate(cross_sections.items())],
                    dtype=ProcessIndex.dtype_process)

@pytest.mark.parametrize('pol, key', [((-1, -1), 'LL'), ((-1, 1), 'LR'), ((1, -1), 'RL'), ((1, 1), 'RR'), ((0, 0), 'NN'), ((0., 0.), 'NN')])
def test_get_pol_key(pol, key):
    assert get_pol_key(*pol) == key

@pytest.mark.parametrize('pol', [(0, 1), (-1, 0), (1, 0), (0, -1), (-0.8, 0.3), (0, 0.3)])
def test_get_pol_key_invalid(pol):
    with pytest.raises(Exception, match='Invalid polarization'):
        get_pol_key(*pol)

def test_unpolarized_weight_is_independent_of_the_polarization():
    assert get_w_pol(0, 0) == 1.
    assert sample_weight(2., (0, 0), n_gen=4, lum_inv_ab=1.) == 500.

def test_combined_cross_section_unpolarized():
    processes = make_processes({ 'e2e2h_NN': 6.76, 'other_NN': 1. })

    assert combined_cross_section(processes, 'e2e2h', 0, 0) == pytest.approx(6.76)
    assert combined_cross_section(processes, ['e2e2h', 'other'], 0, 0) == pytest.approx(7.76)

def test_combined_cross_section_polarized():
    cross_sections = { 'p_LL': 1., 'p_LR': 2., 'p_RL': 3., 'p_RR': 4. }
    expected = np.dot(w_prefacs(-0.8, 0.3), list(cross_sections.values()))

    assert combined_cross_section(make_processes(cross_sections), 'p', -0.8, 0.3) == pytest.approx(expected)

def test_combined_cross_section_missing_entries_do_not_contribute():
    processes = make_processes({ 'p_LR': 2., 'p_RL': 3. })

    assert combined_cross_section(processes, 'p', -0.8, 0.3) == pytest.approx(0.585 * 2. + 0.035 * 3., rel=1e-3)
    assert combined_cross_section(processes, 'missing', 0, 0) == 0.

def test_combined_cross_section_unpolarized_from_polarized_samples():
    assert combined_cross_section(make_processes({ 'p_LR': 2., 'p_RL': 4. }), 'p', 0, 0) == pytest.approx(1.5)
