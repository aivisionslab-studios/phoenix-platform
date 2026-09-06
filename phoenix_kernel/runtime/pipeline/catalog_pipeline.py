import json
from pathlib import Path
from phoenix_kernel.runtime.contracts.model_contracts import (ModelDescriptor, ModelArchitecture, 
    GenerationProfile, ModelNotFound, MissingComponent, CatalogInconsistency)

class CatalogLoader:
    @staticmethod
    def load(catalog_path: Path) -> dict:
        if not catalog_path.exists():
            raise ModelNotFound("Catalog file not found.")
        with open(catalog_path, "r", encoding="utf-8") as f:
            return json.load(f)

class CatalogValidator:
    @staticmethod
    def validate(model_id: str, catalog_data: dict) -> dict:
        info = catalog_data.get(model_id)
        if not info:
            raise ModelNotFound(f"Model '{model_id}' not found in catalog.")
        if "architecture" not in info:
            raise CatalogInconsistency(f"Model '{model_id}' missing 'architecture'.")
        if "filename" not in info:
            raise CatalogInconsistency(f"Model '{model_id}' missing 'filename'.")
        return info

class PathResolver:
    @staticmethod
    def resolve_paths(model_id: str, catalog_info: dict, models_base_dir: Path) -> ModelDescriptor:
        subfolder = catalog_info.get("destination_folder", "StableDiffusion")
        dest_dir = models_base_dir / subfolder
        
        model_path = dest_dir / catalog_info["filename"]
        
        components = {}
        for key, val in catalog_info.get("components", {}).items():
            comp_file = val.get("filename")
            if comp_file:
                components[key] = dest_dir / comp_file
                
        arch_str = catalog_info.get("architecture", "SD15")
        try:
            architecture = ModelArchitecture(arch_str)
        except ValueError:
            raise CatalogInconsistency(f"Unknown architecture '{arch_str}'.")

        gen_data = catalog_info.get("default_generation", {})
        profile = GenerationProfile(
            steps=gen_data.get("steps", 20),
            cfg=gen_data.get("cfg", 7.0),
            width=gen_data.get("width", 512),
            height=gen_data.get("height", 512)
        )
        
        return ModelDescriptor(
            architecture=architecture,
            model_path=model_path,
            components=components,
            generation_profile=profile
        )

class FileValidator:
    @staticmethod
    def validate_disk(desc: ModelDescriptor):
        if not desc.model_path.exists():
            raise MissingComponent(f"Model file '{desc.model_path.name}' not found on disk.")
        # Components are validated by the Builder during command generation
