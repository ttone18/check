import logbook
from core.config import load_all_configs
from core.models import *

LOG = logbook.Logger(__name__)
CONFIGS = load_all_configs()
THRESHOLDS = CONFIGS.get('thresholds', {})
GPFS_MOUNT_PATH = THRESHOLDS.get("gpfs_mount_path", "/gpfs/pvc")

def _create_failure(host_info, type, extra):
    return {
        KEY_HOST: host_info[0], KEY_HOSTNAME: host_info[1],
        KEY_TYPE: type, KEY_EXTRA: extra, KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}


def get_gpfs_status_command():
    return f"if [ -d '{GPFS_MOUNT_PATH}' ]; then echo 'mounted'; else echo 'not_mounted'; fi"

def parse_gpfs_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[GPFS] Command execution failed: {result_payload['error']}")

    output = result_payload['output'].strip()

    if output == 'not_mounted':
        return _create_failure(host_info, TYPE_GPFS_STATUS, f"GPFS directory '{GPFS_MOUNT_PATH}' is not mounted.")
    
    if output != 'mounted':
        return _create_failure(host_info, TYPE_UNK, f"[GPFS] Unexpected output from check command: '{output}'")

    return _create_success([TYPE_GPFS_STATUS, TYPE_SHUTDOWN])
