from __future__ import annotations
import importlib.util
import logging
from pathlib import Path
from core.kernel.kernel import PlatformKernel

logger = logging.getLogger(__name__)

def load_plugins(kernel: PlatformKernel, plugins_dir: str = "plugins") -> None:
    """Varre o diretório de plugins e registra Engines/Connectors dinamicamente."""
    plugins_path = Path(plugins_dir)
    if not plugins_path.exists():
        plugins_path.mkdir(parents=True, exist_ok=True)
        logger.info("PluginLoader: Created plugins directory at %s", plugins_path.resolve())
        return

    logger.info("PluginLoader: Scanning for plugins in %s...", plugins_path.resolve())
    
    # Adiciona o diretório de plugins ao sys.path temporariamente para imports relativos funcionarem
    import sys
    if str(plugins_path.absolute()) not in sys.path:
        sys.path.insert(0, str(plugins_path.absolute()))

    for plugin_file in plugins_path.glob("*.py"):
        if plugin_file.name.startswith("_"):
            continue
            
        module_name = plugin_file.stem
        try:
            spec = importlib.util.spec_from_file_location(module_name, plugin_file)
            if not spec or not spec.loader:
                continue
                
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Procura por uma função 'register' no módulo
            if hasattr(module, "register"):
                logger.info("PluginLoader: Loading plugin '%s'...", module_name)
                module.register(kernel)
            else:
                logger.warning("PluginLoader: Plugin '%s' missing 'register(kernel)' function.", module_name)
                
        except Exception as exc:
            logger.error("PluginLoader: Failed to load plugin '%s': %s", module_name, exc)
