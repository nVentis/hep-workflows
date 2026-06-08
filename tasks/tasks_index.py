from .tasks_abstract import AbstractIndex

class RawIndex(AbstractIndex):
    def requires(self):
        from .framework import configurations
        return configurations.get(str(self.tag)).raw_index_requires(self)

class AnalysisIndex(AbstractIndex):
    def requires(self):
        from .framework import configurations
        return configurations.get(str(self.tag)).analysis_index_requires(self)
    
    def slcio_files(self):
        reco_final_target_collection = self.input()[0]['collection']
        
        # reco_final_target_collection[i][0] is directory, [i][1] is file
        reco_slcio_files = [reco_final_target_collection[i][1].path for i in range(len(reco_final_target_collection))]
        
        return reco_slcio_files