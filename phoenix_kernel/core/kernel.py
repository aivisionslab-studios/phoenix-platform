"""
kernel.py (phoenix_kernel.core)

PHX-FIX (auditoria 2026-08-04): `MissionKernel` nunca existiu neste módulo —
`tests/test_mission_kernel.py` importava `from phoenix_kernel.core.kernel
import MissionKernel`, e como o arquivo/classe não existia, a suíte de
testes inteira falhava na COLETA (nem chegava a rodar um teste sequer).

Este é um portão de aprovação simples para uma única "missão ativa" por vez:
o planner (MissionPlanner) cria a Mission, este kernel a registra e a
mantém pendente de aprovação humana antes de qualquer execução real.

O comportamento abaixo foi derivado diretamente das asserções já existentes
em tests/test_mission_kernel.py (register -> WAITING_APPROVAL,
approve_active_mission -> APPROVED, reject_active_mission -> limpa o
estado, aprovar/rejeitar sem missão ativa -> NoActiveMissionError).
"""

from __future__ import annotations

from .models import Mission
from .enums import MissionStatus
from .exceptions import NoActiveMissionError


class MissionKernel:
    """Portão de aprovação de uma única missão ativa por vez."""

    def __init__(self) -> None:
        self._active: Mission | None = None

    def register(self, mission: Mission) -> Mission:
        """Registra `mission` como a missão ativa, marcando-a como
        aguardando aprovação. Retorna a MESMA instância (não uma cópia)."""
        mission.status = MissionStatus.WAITING_APPROVAL
        self._active = mission
        return mission

    def get_active(self) -> Mission | None:
        return self._active

    def approve_active_mission(self) -> Mission:
        if self._active is None:
            raise NoActiveMissionError("Nenhuma missão ativa para aprovar.")
        self._active.status = MissionStatus.APPROVED
        return self._active

    def reject_active_mission(self) -> None:
        if self._active is None:
            raise NoActiveMissionError("Nenhuma missão ativa para rejeitar.")
        self._active.status = MissionStatus.REJECTED
        self._active = None
