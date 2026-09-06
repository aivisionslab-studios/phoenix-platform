from pathlib import Path
import json
import platform
import socket
import uuid

from google.cloud import firestore
from google.oauth2 import service_account


ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = ROOT / "data" / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

CREDENTIAL_FILE = CONFIG_DIR / "firestore_credentials.json"
EXAMPLE_FILE = CONFIG_DIR / "firestore_credentials.example.json"
MACHINE_FILE = CONFIG_DIR / "machine.json"


def load_machine_id():

    if MACHINE_FILE.exists():
        return json.loads(MACHINE_FILE.read_text(encoding="utf-8"))["machine_id"]

    machine_id = str(uuid.uuid4())

    MACHINE_FILE.write_text(
        json.dumps(
            {
                "machine_id": machine_id
            },
            indent=4
        ),
        encoding="utf-8"
    )

    return machine_id


def create_example():

    if EXAMPLE_FILE.exists():
        return

    EXAMPLE_FILE.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "",
                "private_key": "",
                "client_email": ""
            },
            indent=4
        ),
        encoding="utf-8"
    )


def connect():

    credentials = service_account.Credentials.from_service_account_file(
        CREDENTIAL_FILE
    )

    return firestore.Client(
        project=credentials.project_id,
        credentials=credentials
    )


def bootstrap():

    create_example()

    if not CREDENTIAL_FILE.exists():
        print("Credencial não encontrada.")
        print(CREDENTIAL_FILE)
        return

    machine_id = load_machine_id()

    db = connect()

    db.collection("machines").document(machine_id).set(
        {
            "hostname": socket.gethostname(),
            "computer": platform.node(),
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
            "online": True,
            "telemetry_enabled": True,
            "version": "3.0.0",
            "last_seen": firestore.SERVER_TIMESTAMP
        },
        merge=True
    )

    db.collection("machines").document(machine_id)\
        .collection("hardware")\
        .document("current")\
        .set({}, merge=True)

    db.collection("machines").document(machine_id)\
        .collection("status")\
        .document("current")\
        .set({}, merge=True)

    print("=====================================")
    print("Firestore inicializado com sucesso!")
    print(f"Machine ID : {machine_id}")
    print(f"Hostname   : {socket.gethostname()}")
    print("=====================================")


if __name__ == "__main__":
    bootstrap()