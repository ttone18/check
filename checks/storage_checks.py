import logbook
from core.models import (
    KEY_HOST, KEY_HOSTNAME, KEY_TYPE, KEY_EXTRA, KEY_SUCCESS, KEY_TYPES,
    TYPE_GPFS_STATUS, TYPE_SHUTDOWN, TYPE_UNK
)

LOG = logbook.Logger(__name__)

def _create_failure(host_info, type, extra):
    return {
        KEY_HOST: host_info[0], KEY_HOSTNAME: host_info[1],
        KEY_TYPE: type, KEY_EXTRA: extra, KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}


def get_gpfs_status_command():
    return "if [ -d '/gpfs/pvc' ]; then echo 'mounted'; else echo 'not_mounted'; fi"

def parse_gpfs_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[GPFS] Command execution failed: {result_payload['error']}")

    output = result_payload['output'].strip()

    if output == 'not_mounted':
        return _create_failure(host_info, TYPE_GPFS_STATUS, "GPFS directory /gpfs/pvc is not mounted.")
    
    if output != 'mounted':
        return _create_failure(host_info, TYPE_UNK, f"[GPFS] Unexpected output from check command: '{output}'")

    return _create_success([TYPE_GPFS_STATUS, TYPE_SHUTDOWN])
