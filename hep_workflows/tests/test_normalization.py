import numpy as np
import pytest

pytest.importorskip('uproot')

from hep_workflows.utils.normalization import (
    CHUNK_SPLIT_MODES, construct_sample_groups, dtype_common, get_process_normalization, get_sample_chunk_splits,
    process_custom_statistics
)
from hep_workflows.utils.ProcessIndex import ProcessIndex

def polarizations(proc_pol:str)->tuple[int, int]:
    """(pol_e, pol_p) of e.g. 'e2e2h_LR'"""
    return tuple(-1 if key == 'L' else 1 for key in proc_pol[-2:])

def make_samples(rows:list[tuple])->np.ndarray:
    """rows: (process, proc_pol, n_events, location)"""
    return np.array([
        (sid, 1, process, proc_pol, n_events, *polarizations(proc_pol), location, 'MCParticle')
        for sid, (process, proc_pol, n_events, location) in enumerate(rows)
    ], dtype=ProcessIndex.dtype_sample)

def make_processes(rows:list[tuple])->np.ndarray:
    """rows: (process, proc_pol, cross_sec)"""
    return np.array([
        (pid, process, proc_pol, *polarizations(proc_pol), cross_sec, 0., 0)
        for pid, (process, proc_pol, cross_sec) in enumerate(rows)
    ], dtype=ProcessIndex.dtype_process)

@pytest.fixture
def samples():
    return make_samples([
        ('e2e2h', 'e2e2h_LR', 100, '/data/a.0.slcio'),
        ('e2e2h', 'e2e2h_LR', 100, '/data/a.1.slcio'),
        ('e2e2h', 'e2e2h_RL', 50, '/data/b.0.slcio'),
    ])

@pytest.fixture
def processes():
    return make_processes([
        ('e2e2h', 'e2e2h_LR', 17.),
        ('e2e2h', 'e2e2h_RL', 11.),
    ])

@pytest.fixture
def process_normalization(processes, samples):
    return get_process_normalization(processes, samples)

class TestProcessNormalization:
    def test_totals_and_default_target(self, process_normalization):
        # sorted by proc_pol
        assert process_normalization['proc_pol'].tolist() == ['e2e2h_LR', 'e2e2h_RL']
        assert process_normalization['n_events_tot'].tolist() == [200, 50]
        assert process_normalization['n_events_target'].tolist() == [200, 50]

    def test_event_weight_matches_expectation(self, process_normalization):
        assert np.allclose(process_normalization['event_weight'] * process_normalization['n_events_tot'],
                           process_normalization['n_events_expected'], rtol=1e-5)
        assert np.all(process_normalization['n_events_expected'] > 0)

    @pytest.mark.parametrize('ratio, expected', [(0.5, [100, 25]), (1., [200, 50]), (2., [200, 50]), (None, [200, 50])])
    def test_ratio_by_total(self, processes, samples, ratio, expected):
        pn = get_process_normalization(processes, samples, RATIO_BY_TOTAL=ratio)
        assert pn['n_events_target'].tolist() == expected

class TestCustomStatistics:
    def test_fraction_of_total(self, process_normalization):
        pn = process_custom_statistics(np.copy(process_normalization), [(0.25, ['e2e2h'])])
        assert pn['n_events_target'].tolist() == [50, 13]

    def test_target_is_bounded_by_available_events(self, process_normalization):
        pn = process_custom_statistics(np.copy(process_normalization), [(1e6, 'e2e2h', 'expected')])
        assert pn['n_events_target'].tolist() == pn['n_events_tot'].tolist()

    def test_unknown_process_is_ignored(self, process_normalization):
        pn = process_custom_statistics(np.copy(process_normalization), [(0., ['other'])])
        assert pn['n_events_target'].tolist() == [200, 50]

    def test_invalid_entry(self, process_normalization):
        with pytest.raises(Exception):
            process_custom_statistics(np.copy(process_normalization), [(1.,)])

class TestChunkSplitsOneToMany:
    def split(self, samples, pn, atpe=None, max_time=7200, **kwargs):
        return get_sample_chunk_splits(samples, atpe, pn, MAXIMUM_TIME_PER_JOB=max_time,
                                       split_mode=CHUNK_SPLIT_MODES['ONE_TO_MANY'], **kwargs)

    def test_one_chunk_per_sample_without_timing(self, samples, process_normalization):
        chunks = self.split(samples, process_normalization)

        assert chunks['branch'].tolist() == [0, 1, 2]
        assert chunks['chunk_size'].tolist() == [100, 100, 50]
        assert chunks['chunk_start'].tolist() == [0, 0, 0]
        assert chunks['n_chunks_in_sample'].tolist() == [1, 1, 1]

    def test_all_events_are_accounted_for_exactly_once(self, samples, process_normalization):
        # 1 s/event with 30 s/job: 100 events -> 4 even chunks of 25
        atpe = np.array([('e2e2h', 1., 1., 100, 1.)], dtype=[('process', '<U64'), ('tAvg', 'f'), ('tMax', 'f'), ('n_processed', 'i'), ('tPE', 'f')])
        chunks = self.split(samples, process_normalization, atpe, max_time=30)

        assert chunks['chunk_size'].max() <= 30
        for location, n_events in zip(samples['location'], samples['n_events']):
            sample_chunks = chunks[chunks['location'] == location]

            assert sample_chunks['chunk_size'].sum() == n_events
            assert np.all(sample_chunks['n_chunks_in_sample'] == len(sample_chunks))
            # chunks are consecutive
            starts = sample_chunks['chunk_start']
            assert starts.tolist() == np.cumsum([0] + sample_chunks['chunk_size'].tolist()[:-1]).tolist()

        assert chunks['branch'].tolist() == list(range(len(chunks)))

    def test_target_is_respected(self, samples, processes):
        pn = get_process_normalization(processes, samples, RATIO_BY_TOTAL=0.5)
        chunks = self.split(samples, pn)

        for proc_pol, n_target in zip(pn['proc_pol'], pn['n_events_target']):
            assert chunks[chunks['proc_pol'] == proc_pol]['chunk_size'].sum() == n_target

    def test_zero_target_gives_no_chunks(self, samples, processes):
        pn = get_process_normalization(processes, samples, RATIO_BY_TOTAL=0.)
        assert len(self.split(samples, pn)) == 0

class TestChunkSplitsManyToMany:
    def test_branch_size_is_sum_of_sub_branches(self, samples, process_normalization):
        chunks = get_sample_chunk_splits(samples, None, process_normalization, split_mode=CHUNK_SPLIT_MODES['MANY_TO_MANY'])

        for branch in np.unique(chunks['branch']):
            rows = chunks[chunks['branch'] == branch]
            assert np.all(rows['branch_size'] == rows['sub_branch_size'].sum())

        assert chunks['sub_branch_size'].sum() == samples['n_events'].sum()

    def test_grouped(self, processes):
        # two reco chunks of e2e2h_LR originating from the same source file are put together, the e2e2h_RL one is separate
        reco_chunks = np.array([
            (0, 0, 'e2e2h', 'e2e2h_LR', '/data/src_a.slcio'),
            (1, 1, 'e2e2h', 'e2e2h_LR', '/data/src_a.slcio'),
            (2, 2, 'e2e2h', 'e2e2h_RL', '/data/src_b.slcio'),
        ], dtype=dtype_common)
        analysis_samples = make_samples([
            ('e2e2h', 'e2e2h_LR', 100, '/data/reco/src_a.0-1-0.slcio'),
            ('e2e2h', 'e2e2h_LR', 100, '/data/reco/src_a.0-1-1.slcio'),
            ('e2e2h', 'e2e2h_RL', 50, '/data/reco/src_b.0-1-2.slcio'),
        ])
        sample_groups = construct_sample_groups(reco_chunks, analysis_samples)

        assert sample_groups == { 'e2e2h_LR': { 'src_a': [0, 1] }, 'e2e2h_RL': { 'src_b': [2] } }

        pn = get_process_normalization(processes, analysis_samples)
        chunks = get_sample_chunk_splits(analysis_samples, None, pn, split_mode=CHUNK_SPLIT_MODES['MANY_TO_MANY'], sample_groups=sample_groups)

        assert chunks['branch'].tolist() == [0, 0, 1]
        assert chunks['src_bname'].tolist() == ['src_a', 'src_a', 'src_b']
        assert chunks['branch_size'].tolist() == [200, 200, 50]

class TestConstructSampleGroups:
    def test_branch_extraction_ignores_generator_version(self):
        # the "-3.1.5" of the Whizard version must not be mistaken for the branch number
        locations = ['/d/E250.Pe2e2h.Gwhizard-3.1.5.eL.pR.0.0-1-7.edm4hep.root']
        reco_chunks = np.array([(7, 0, 'e2e2h', 'e2e2h_LR', '/g/E250.Pe2e2h.Gwhizard-3.1.5.eL.pR.0.slcio')],
                               dtype=dtype_common)
        samples = make_samples([('e2e2h', 'e2e2h_LR', 10, loc) for loc in locations])

        assert construct_sample_groups(reco_chunks, samples) == { 'e2e2h_LR': { 'E250.Pe2e2h.Gwhizard-3.1.5.eL.pR.0': [0] } }

    def test_location_without_branch(self):
        reco_chunks = np.array([(0, 0, 'p', 'p_LR', '/g/a.slcio')],
                               dtype=dtype_common)

        with pytest.raises(Exception, match='source branch'):
            construct_sample_groups(reco_chunks, make_samples([('p', 'p_LR', 1, '/d/no_branch.slcio')]))
