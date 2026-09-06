import pytest
from phoenix_kernel.core.models import Mission, MissionStep
from phoenix_kernel.core.enums import MissionStatus, MissionAction
from phoenix_kernel.core.planner import MissionPlanner
from phoenix_kernel.core.kernel import MissionKernel
from phoenix_kernel.core.exceptions import NoActiveMissionError

def test_planner_creates_mission_with_correct_steps():
    planner = MissionPlanner()
    mission = planner.create("instalar ollama")
    assert isinstance(mission, Mission)
    assert mission.intent == "instalar ollama"
    assert len(mission.steps) == 1
    assert mission.steps[0].target == "ollama"
    assert mission.steps[0].action == MissionAction.INSTALL_PACKAGE
    assert mission.status == MissionStatus.CREATED

def test_kernel_registers_mission_and_sets_waiting_approval():
    kernel = MissionKernel()
    planner = MissionPlanner()
    mission = planner.create("instalar comfyui")
    registered_mission = kernel.register(mission)
    assert registered_mission.status == MissionStatus.WAITING_APPROVAL
    assert kernel.get_active() is not None

def test_kernel_approves_active_mission():
    kernel = MissionKernel()
    planner = MissionPlanner()
    mission = planner.create("testar ambiente")
    kernel.register(mission)
    approved_mission = kernel.approve_active_mission()
    assert approved_mission.status == MissionStatus.APPROVED

def test_kernel_rejects_active_mission():
    kernel = MissionKernel()
    planner = MissionPlanner()
    mission = planner.create("testar ambiente")
    kernel.register(mission)
    kernel.reject_active_mission()
    assert kernel.get_active() is None

def test_kernel_approve_without_active_mission_raises_error():
    kernel = MissionKernel()
    with pytest.raises(NoActiveMissionError):
        kernel.approve_active_mission()

def test_to_dict_serialization():
    planner = MissionPlanner()
    mission = planner.create("instalar ollama")
    data = mission.to_dict()
    assert data["intent"] == "instalar ollama"
    assert data["steps"][0]["target"] == "ollama"
    assert data["steps"][0]["action"] == "INSTALL_PACKAGE"
    assert data["status"] == "created"
    assert len(data["id"]) == 36 

def test_each_mission_has_unique_id():
    planner = MissionPlanner()
    a = planner.create("a")
    b = planner.create("b")
    assert a.id != b.id

def test_registered_mission_is_same_instance():
    planner = MissionPlanner()
    kernel = MissionKernel()
    mission = planner.create("instalar ollama")
    registered = kernel.register(mission)
    assert registered is mission

def test_status_is_serialized_as_string():
    mission = Mission()
    data = mission.to_dict()
    assert data["status"] == "created"
    assert isinstance(data["status"], str)

def test_step_parameters_are_serialized():
    planner = MissionPlanner()
    mission = planner.create("instalar ollama")
    data = mission.to_dict()
    assert data["steps"][0]["parameters"]["provider"] == "docker"

def test_step_action_is_enum_instance():
    planner = MissionPlanner()
    mission = planner.create("instalar ollama")
    assert isinstance(mission.steps[0].action, MissionAction)

def test_metadata_is_serialized():
    mission = Mission(intent="test", metadata={"blueprint_id": "bp_001"})
    data = mission.to_dict()
    assert data["metadata"]["blueprint_id"] == "bp_001"

def test_parameters_default_to_empty_dict():
    step = MissionStep(step=1, action=MissionAction.VALIDATE, target="env", description="desc")
    assert step.parameters == {}
