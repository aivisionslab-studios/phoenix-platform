from __future__ import annotations
import logging
from pathlib import Path

def setup_file_logging(workspace: Path, level: int = logging.INFO) -> None:
    log_dir = workspace / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'platform.log'
    formatter = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)
    logging.info('File logging initialized at %s', log_file)
