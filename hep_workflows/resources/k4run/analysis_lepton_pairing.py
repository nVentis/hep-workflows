"""Example k4run steering file for the channel-specific analysis (AnalysisRuntime/AnalysisFinal) on the
output of the high-level reconstruction (RecoRuntime/RecoFinal, see high_level_reco.py), i.e.
files containing the ISOLeptons and PandoraPFOsWithoutIsoLep collections.

Only runs the isolated lepton pairing (the LeptonPairing processor of the ZHH repository, which is
not part of the key4hep stack: its library is attached via --marlinDll).

Usage: k4run analysis_lepton_pairing.py --inputFiles <files> --compactFile <compact file> --outputFile <file>
           [--marlinDll <libZHHProcessors.so> ...] [--rootFile <file>] [-n <nevents>]
"""

import os

from Gaudi.Configuration import INFO
from Configurables import EventDataSvc, GeoSvc, MarlinProcessorWrapper
from k4FWCore import ApplicationMgr, IOSvc
from k4FWCore.parseArgs import parser
from k4MarlinWrapper.io_helpers import IOHandlerHelper

parser.add_argument("--inputFiles", action="extend", nargs="+", metavar=["file1", "file2"],
                    help="One or multiple input files", required=True)
parser.add_argument("--outputFile", help="Name of the output edm4hep file", default="out_ANA.edm4hep.root")
parser.add_argument("--compactFile", help="Path to the DD4hep XML compact file defining the detector geometry", required=True)
parser.add_argument("--MCParticleCollectionName", default="MCParticle",
                    help="Name of the MCParticle collection if the input are LCIO files (given to all tasks running Marlin/k4run)")
parser.add_argument("--marlinDll", action="extend", nargs="+", default=[],
                    help="Marlin processor libraries to attach in addition to the key4hep ones (prepended to $MARLIN_DLL)")
parser.add_argument("--rootFile", help="Name of the ROOT file the LeptonPairing processor fills its TTree into",
                    default="LeptonPairing.root")

args = parser.parse_known_args()[0]

# the wrapper reads MARLIN_DLL when it initializes, i.e. after this script has been parsed
if args.marlinDll:
    os.environ["MARLIN_DLL"] = ":".join(args.marlinDll + [os.environ.get("MARLIN_DLL", "")])

algList = []
svcList = []

evtsvc = EventDataSvc("EventDataSvc")
svcList.append(evtsvc)
iosvc = IOSvc()

geoSvc = GeoSvc("GeoSvc")
geoSvc.detectors = [args.compactFile]
geoSvc.EnableGeant4Geo = False
svcList.append(geoSvc)

io_handler = IOHandlerHelper(algList, iosvc)
io_handler.add_reader(args.inputFiles)

MyLeptonPairing = MarlinProcessorWrapper("MyLeptonPairing")
MyLeptonPairing.ProcessorType = "LeptonPairing"
MyLeptonPairing.Parameters = {
    "IsoLepCollection": ["ISOLeptons"],
    "PFOsWOIsoLepCollection": ["PandoraPFOsWithoutIsoLep"],
    "LepPairCollection": ["LeptonPair"],
    "PFOsWOLepPairCollection": ["PandoraPFOsWithoutLepPair"],
    "IsoLepPairCollection": ["IsoLeptonPair"],
    "fillRootTree": ["true"],
    "RootFile": [args.rootFile],
}
algList.append(MyLeptonPairing)

io_handler.add_edm4hep_writer(args.outputFile, ["keep *"])
io_handler.finalize_converters()

# The converters added by IOHandlerHelper.finalize_converters name the MCParticle collection of the
# output "MCParticles", but only convert the LCIO collection "MCParticle". Other names (e.g.
# "MCParticlesSkimmed" in the output of SGV) are mapped here, so that the output always has "MCParticles"
if args.MCParticleCollectionName not in ("MCParticle", "MCParticles"):
    for alg in algList:
        if getattr(alg, "Lcio2EDM4hepTool", None) is not None:
            converter = alg.Lcio2EDM4hepTool
            converter.collNameMapping = {**converter.collNameMapping, args.MCParticleCollectionName: "MCParticles"}

app_mgr = ApplicationMgr(TopAlg=algList, EvtSel="NONE", EvtMax=-1, ExtSvc=svcList, OutputLevel=INFO)
