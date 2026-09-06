from abc import ABC, abstractmethod
from typing import List
from phoenix_kernel.runtime.contracts.model_contracts import ModelDescriptor, GenerationProfile

class ICommandBuilder(ABC):
    @abstractmethod
    def build(self, exe_path: str, desc: ModelDescriptor, profile: GenerationProfile, prompt: str, output_file: str) -> List[str]:
        pass
