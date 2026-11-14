"""Helper script for the integration tests, run in the software environment of setup.sh (pyLCIO, podio):

    python event_numbers.py read <file>...       prints {file: [event numbers in file order]} as JSON
    python event_numbers.py write <dir> <n> <offset>
                                                  writes <dir>/in.slcio (one run header) and <dir>/in.edm4hep.root,
                                                  each with <n> events numbered offset, offset+1, ...

Event numbers are taken from the LCIO event, or from the EventHeader collection for EDM4hep files.
"""

import json
import sys

def read_lcio(path:str)->list[int]:
    from pyLCIO import IOIMPL

    reader = IOIMPL.LCFactory.getInstance().createLCReader()
    reader.open(path)
    numbers = [int(event.getEventNumber()) for event in reader]
    reader.close()

    return numbers

def read_edm4hep(path:str)->list[int]:
    from podio import root_io

    return [int(frame.get('EventHeader')[0].getEventNumber()) for frame in root_io.Reader(path).get('events')]

def write(directory:str, n:int, offset:int):
    import podio, edm4hep
    from podio import root_io
    from pyLCIO import EVENT, IMPL, IOIMPL

    writer = IOIMPL.LCFactory.getInstance().createLCWriter()
    writer.open(f'{directory}/in.slcio', EVENT.LCIO.WRITE_NEW)
    run_header = IMPL.LCRunHeaderImpl()
    run_header.setRunNumber(7)
    writer.writeRunHeader(run_header)

    for i in range(n):
        event = IMPL.LCEventImpl()
        event.setRunNumber(7)
        event.setEventNumber(offset + i)
        event.addCollection(IMPL.LCCollectionVec(EVENT.LCIO.MCPARTICLE), 'MCParticle')
        writer.writeEvent(event)

    writer.close()

    writer = root_io.Writer(f'{directory}/in.edm4hep.root')
    for i in range(n):
        frame = podio.Frame()
        headers = edm4hep.EventHeaderCollection()
        header = headers.create()
        header.setEventNumber(offset + i)
        header.setRunNumber(7)
        frame.put(headers, 'EventHeader')
        frame.put(edm4hep.MCParticleCollection(), 'MCParticles')
        writer.write_frame(frame, 'events')

    # podio finishes its writers at exit (finishing explicitly as well crashes podio <= 1.1)

if __name__ == '__main__':
    if sys.argv[1] == 'write':
        write(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
    elif sys.argv[1] == 'read':
        print(json.dumps({ path: read_lcio(path) if path.endswith('.slcio') else read_edm4hep(path) for path in sys.argv[2:] }))
    else:
        raise Exception(f'Unknown command <{sys.argv[1]}>')
