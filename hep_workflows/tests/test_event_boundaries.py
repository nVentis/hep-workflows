"""Integration test of the event boundaries of chunks: the commands built by AbstractRecoAna.build_run_command for
consecutive chunks of one sample (n_events_skip=chunk_start, n_events_max=chunk_size) must process exactly the
events [chunk_start, chunk_start + chunk_size), i.e. neighbouring chunks must neither overlap nor leave gaps. This is
checked for Marlin and k4run, with LCIO and EDM4hep input, on small files with known event numbers, using minimal
steering files instead of a real reconstruction (runs within ~1-2 min). In addition, the number of events
count_events_command reports (nEvtSum of meta.json) must match the events actually processed.

LCIO's readStream counts run headers as records, so MaxRecordNumber for Marlin depends on whether events are skipped;
getting this wrong makes every chunk overlap with the next by one event.

Run with `pytest -m integration hep_workflows/tests/test_event_boundaries.py`.
"""

import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest

from .conftest import SoftwareEnvironment

pytest.importorskip('law')
from hep_workflows.tasks_reco_ana import AbstractRecoAna

pytestmark = pytest.mark.integration

EVENT_NUMBERS = Path(__file__).resolve().parent / 'event_numbers.py'

N_EVENTS = 23
# event numbers differ from the indices in the file, so that one cannot be mistaken for the other
EVENT_OFFSET = 100
# (chunk_start, chunk_size): consecutive chunks covering the whole sample, the last one shorter and one
# that asks for more events than there are left (as at the end of a sample)
CHUNKS = [(0, 8), (8, 8), (16, 7)]
CHUNKS_PAST_END = [(16, 10)]

MARLIN_STEERING = """<marlin>
 <execute><processor name="Output"/></execute>
 <global>
  <parameter name="LCIOInputFiles"></parameter>
  <parameter name="MaxRecordNumber" value="0"/>
  <parameter name="SkipNEvents" value="0"/>
  <parameter name="SupressCheck" value="false"/>
  <parameter name="Verbosity" options="DEBUG0-4,MESSAGE0-4,WARNING0-4,ERROR0-4,SILENT">WARNING</parameter>
 </global>
 <processor name="Output" type="LCIOOutputProcessor">
  <parameter name="LCIOOutputFile" type="string">out.slcio</parameter>
  <parameter name="LCIOWriteMode" type="string">WRITE_NEW</parameter>
 </processor>
</marlin>
"""

# same IO setup as the steering files in resources/k4run, without any reconstruction
K4RUN_STEERING = """from Gaudi.Configuration import WARNING
from Configurables import EventDataSvc, MarlinProcessorWrapper
from k4FWCore import ApplicationMgr, IOSvc
from k4FWCore.parseArgs import parser
from k4MarlinWrapper.io_helpers import IOHandlerHelper

parser.add_argument("--inputFiles", action="extend", nargs="+")
parser.add_argument("--outputFile", default="out.edm4hep.root")
parser.add_argument("--compactFile", default="")
args = parser.parse_known_args()[0]

algList = []
io_handler = IOHandlerHelper(algList, IOSvc())
io_handler.add_reader(args.inputFiles)

status = MarlinProcessorWrapper("Status")
status.ProcessorType = "Statusmonitor"
status.Parameters = {"HowOften": ["1"]}
algList.append(status)

io_handler.add_edm4hep_writer(args.outputFile, ["keep *"])
io_handler.finalize_converters()

ApplicationMgr(TopAlg=algList, EvtSel="NONE", EvtMax=-1, ExtSvc=[EventDataSvc("EventDataSvc")], OutputLevel=WARNING)
"""

# (uses_k4run, input file, output file)
CASES = [
    pytest.param(False, 'in.slcio', 'out.slcio', id='marlin-lcio'),
    pytest.param(True, 'in.slcio', 'out.edm4hep.root', id='k4run-lcio'),
    pytest.param(True, 'in.edm4hep.root', 'out.edm4hep.root', id='k4run-edm4hep'),
]

@pytest.fixture(scope='module')
def inputs(software_environment:SoftwareEnvironment, tmp_path_factory)->Path:
    directory = tmp_path_factory.mktemp('event_boundaries')
    result = software_environment.run(shlex.join(['python', str(EVENT_NUMBERS), 'write', str(directory), str(N_EVENTS), str(EVENT_OFFSET)]), timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]

    (directory / 'steering.xml').write_text(MARLIN_STEERING)
    (directory / 'steering.py').write_text(K4RUN_STEERING)

    written = software_environment.event_numbers([directory / 'in.slcio', directory / 'in.edm4hep.root'])
    assert all(numbers == list(range(EVENT_OFFSET, EVENT_OFFSET + N_EVENTS)) for numbers in written.values()), written

    return directory

@pytest.fixture(scope='module')
def has_k4marlinwrapper_io_helpers(software_environment:SoftwareEnvironment)->bool:
    """k4MarlinWrapper.io_helpers, used by the k4run steering files, is missing in older key4hep releases"""
    return software_environment.run('python -c "import k4MarlinWrapper.io_helpers"', timeout=600).returncode == 0

def run_chunks(env:SoftwareEnvironment, inputs:Path, workdir:Path, uses_k4run:bool, input_file:str, output_file:str,
               chunks:list[tuple[int, int]])->tuple[list[list[int]], list[int]]:
    """Runs the commands of build_run_command for each chunk in its own directory. Returns per chunk the
    processed event numbers and the number of events count_events_command reports for an output that is not
    event-wise (e.g. histograms), for which the count is derived from the input"""
    task = SimpleNamespace(uses_k4run=uses_k4run, compact_file='unused.xml',
                           steering_file=str(inputs / ('steering.py' if uses_k4run else 'steering.xml')),
                           parse_constants=lambda: '', parse_globals=lambda: '')

    # no `set -e`: a chunk that fails is reported below with its log
    script = []
    for i, (start, size) in enumerate(chunks):
        steering = dict(executable='k4run' if uses_k4run else 'Marlin', input_files=[str(inputs / input_file)],
                        n_events_skip=start, n_events_max=size, mcp_col_name='MCParticle', output_bname=None, output_file=output_file)

        chunk_dir = workdir / str(i)
        chunk_dir.mkdir()
        script += [f'cd {shlex.quote(str(chunk_dir))}',
                   f'{AbstractRecoAna.build_run_command(task, steering)} > run.log 2>&1',
                   f'( {AbstractRecoAna.count_events_command(task, { **steering, "output_file": "histograms.root" })} ) > n_events.txt']

    result = env.run('\n'.join(script), timeout=1800)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]

    outputs = [workdir / str(i) / output_file for i in range(len(chunks))]
    for output in outputs:
        assert output.is_file(), f'{output} was not written:\n' + (output.parent / 'run.log').read_text()[-3000:]

    processed = env.event_numbers(outputs)
    counted = [int((workdir / str(i) / 'n_events.txt').read_text().split()[-1]) for i in range(len(chunks))]

    return [processed[str(output)] for output in outputs], counted

def expected_events(start:int, size:int)->list[int]:
    return list(range(EVENT_OFFSET + start, EVENT_OFFSET + min(start + size, N_EVENTS)))

@pytest.mark.parametrize('uses_k4run, input_file, output_file', CASES)
def test_chunks_are_disjoint_and_complete(software_environment:SoftwareEnvironment, inputs:Path, tmp_path:Path,
                                          uses_k4run:bool, input_file:str, output_file:str, request):
    if uses_k4run and not request.getfixturevalue('has_k4marlinwrapper_io_helpers'):
        pytest.skip('k4MarlinWrapper.io_helpers not available in this key4hep stack (e.g. use a nightly build, see README)')

    processed, counted = run_chunks(software_environment, inputs, tmp_path, uses_k4run, input_file, output_file, CHUNKS + CHUNKS_PAST_END)

    for (start, size), events, n_counted in zip(CHUNKS + CHUNKS_PAST_END, processed, counted):
        assert events == expected_events(start, size), f'chunk (start={start}, size={size}) processed the wrong events'
        assert n_counted == len(events), f'chunk (start={start}, size={size}): count_events_command reports {n_counted} events, {len(events)} were processed'

    # together, the consecutive chunks cover the sample exactly once
    covered = [event for events in processed[:len(CHUNKS)] for event in events]
    assert covered == list(range(EVENT_OFFSET, EVENT_OFFSET + N_EVENTS))
