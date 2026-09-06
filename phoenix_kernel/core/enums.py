from enum import Enum

class MissionAction(str, Enum):
    INSTALL_PACKAGE = "INSTALL_PACKAGE"
    DOWNLOAD_MODEL = "DOWNLOAD_MODEL"
    VALIDATE_ENVIRONMENT = "VALIDATE_ENVIRONMENT"
    VALIDATE = "VALIDATE"
    CONFIGURE = "CONFIGURE"
    EXECUTE = "EXECUTE"
    START_SERVICE = "START_SERVICE"
    STOP_SERVICE = "STOP_SERVICE"
    CLONE_REPOSITORY = "CLONE_REPOSITORY"
    RUN_BENCHMARK = "RUN_BENCHMARK"
    SWITCH_RUNTIME = "SWITCH_RUNTIME"
    GENERATE_IMAGE = "GENERATE_IMAGE"
    # PHX-NEW: troca/descarrega o modelo de TEXTO carregado no mesmo
    # runtime (llama.cpp), sem trocar de motor - diferente de
    # SWITCH_RUNTIME (que troca entre runtimes: llama.cpp/sdxl/piper).
    # Ver resident_manager.py (_execute_mission_background) e o fix em
    # LlamaCppDriver.start() que agora compara o modelo pedido com o que
    # já está carregado antes de decidir se recarrega.
    LOAD_MODEL = "LOAD_MODEL"
    UNLOAD_MODEL = "UNLOAD_MODEL"

class MissionStatus(str, Enum):
    CREATED = "created"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    PAUSED = "paused"
