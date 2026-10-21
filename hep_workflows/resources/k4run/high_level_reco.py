"""Example k4run steering file for the high-level reconstruction (K4RunHighLevelReco* tasks)
of edm4hep files produced by the low-level reconstruction (K4RunLowLevelReco* tasks), i.e.
files containing a PandoraPFOs and a PrimaryVertex collection.

Runs the following MarlinProcessorWrappers (adapted from
https://github.com/ILDAnaSoft/HInv_ExScalar/blob/main/scripts/steering_example.py):
- FastJetProcessor: exclusive 4-jet clustering of PandoraPFOs
- IsolatedLeptonTaggingProcessor: isolated electrons/muons
- IsolatedPhotonTaggingProcessor: isolated photons
No lepton pairing is done here, see analysis_lepton_pairing.py.

Usage: k4run high_level_reco.py --inputFiles <files> --compactFile <compact file> --outputFile <file> [-n <nevents>]
The isolated lepton MVA weights are detector specific: set --isoElectronWeights/--isoMuonWeights
(e.g. via k4run_arguments), or, by default, the ILD ones from $ILD_CONFIG_DIR (an ILDConfig checkout)
are used.
"""

import os

from Gaudi.Configuration import INFO
from Configurables import EventDataSvc, GeoSvc, MarlinProcessorWrapper
from k4FWCore import ApplicationMgr, IOSvc
from k4FWCore.parseArgs import parser
from k4MarlinWrapper.io_helpers import IOHandlerHelper

parser.add_argument("--inputFiles", action="extend", nargs="+", metavar=["file1", "file2"],
                    help="One or multiple input files", required=True)
parser.add_argument("--outputFile", help="Name of the output edm4hep file", default="out_HLR.edm4hep.root")
parser.add_argument("--compactFile", help="Path to the DD4hep XML compact file defining the detector geometry", required=True)
parser.add_argument("--MCParticleCollectionName", default="MCParticle",
                    help="Name of the MCParticle collection if the input are LCIO files (given to all tasks running Marlin/k4run)")

_ild_weights = os.path.join(os.environ["ILD_CONFIG_DIR"], "IsolatedLeptonTagging/weights") if "ILD_CONFIG_DIR" in os.environ else None
parser.add_argument("--isoElectronWeights", help="Directory of the isolated electron MVA weights",
                    default=f"{_ild_weights}/e1e1h_gg_qqqq_250" if _ild_weights else None, required=_ild_weights is None)
parser.add_argument("--isoMuonWeights", help="Directory of the isolated muon MVA weights",
                    default=f"{_ild_weights}/e2e2h_gg_qqqq_250" if _ild_weights else None, required=_ild_weights is None)

args = parser.parse_known_args()[0]

PFO_COLLECTION = "PandoraPFOs"

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

MyFastJetProcessor = MarlinProcessorWrapper("MyFastJetProcessor")
MyFastJetProcessor.ProcessorType = "FastJetProcessor"
MyFastJetProcessor.Parameters = {
    "algorithm": ["kt_algorithm", "1.3"],
    "clusteringMode": ["ExclusiveNJets", "4"],
    "jetOut": ["FastJets4_Precluster"],
    "recParticleIn": [PFO_COLLECTION],
    "recParticleOut": ["RefinedJets"],
    "recombinationScheme": ["E_scheme"],
    "storeParticlesInJets": ["true"],
}
algList.append(MyFastJetProcessor)

MyIsolatedLeptonTaggingProcessor = MarlinProcessorWrapper("MyIsolatedLeptonTaggingProcessor")
MyIsolatedLeptonTaggingProcessor.ProcessorType = "IsolatedLeptonTaggingProcessor"
MyIsolatedLeptonTaggingProcessor.Parameters = {
    "CosConeLarge": ["0.95"],
    "CosConeSmall": ["0.98"],
    "CutOnTheISOElectronMVA": ["0.5"],
    "CutOnTheISOMuonMVA": ["0.7"],
    "DirOfISOElectronWeights": [args.isoElectronWeights],
    "DirOfISOMuonWeights": [args.isoMuonWeights],
    "InputPandoraPFOsCollection": [PFO_COLLECTION],
    "InputPrimaryVertexCollection": ["PrimaryVertex"],
    "IsSelectingOneIsoLep": ["false"],
    "MaxD0SigForElectron": ["50"],
    "MaxD0SigForMuon": ["20"],
    "MaxEOverPForElectron": ["1.3"],
    "MaxEOverPForMuon": ["0.3"],
    "MaxZ0SigForElectron": ["50"],
    "MaxZ0SigForMuon": ["20"],
    "MinEOverPForElectron": ["0.5"],
    "MinEecalOverTotEForElectron": ["0.9"],
    "MinEyokeForMuon": ["1.2"],
    "MinPForElectron": ["5"],
    "MinPForMuon": ["5"],
    "OutputIsoLeptonsCollection": ["ISOLeptons"],
    "OutputPFOsWithoutIsoLepCollection": ["PandoraPFOsWithoutIsoLep"],
    "UseYokeForMuonID": ["true"],
}
algList.append(MyIsolatedLeptonTaggingProcessor)

IsolatedPhotonTagging = MarlinProcessorWrapper("IsolatedPhotonTagging")
IsolatedPhotonTagging.ProcessorType = "IsolatedPhotonTaggingProcessor"
IsolatedPhotonTagging.Parameters = {
    "CosConeLarge": ["0.95"],
    "CosConeSmall": ["0.98"],
    "InputPandoraPFOsCollection": ["PandoraPFOsWithoutIsoLep"],
    "IsSelectingOneIsoPhoton": ["false"],
    "MinEForPhoton": ["5."],
    "OutputIsoPhotonsCollection": ["IsolatedPhotons"],
    "OutputPFOsWithoutIsoPhotonCollection": ["PandoraPFOsWithoutIsoLepAndPhotons"],
}
algList.append(IsolatedPhotonTagging)

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
