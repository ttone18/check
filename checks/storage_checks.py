import logbook
from core.models import *

LOG = logbook.Logger(__name__)

def _create_failure(node_spec, type, extra):
    return {
        KEY_HOST: node_spec.get('host'), 
        KEY_HOSTNAME: node_spec.get('hostname'),
        KEY_TYPE: type, 
        KEY_EXTRA: extra, 
        KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}


def get_gpfs_status_command(thresholds):
    gpfs_mount_path = thresholds.get("gpfs_mount_path", "/gpfs/pvc")
    return f"if [ -d '{gpfs_mount_path}' ]; then echo 'mounted'; else echo 'not_mounted'; fi"

def parse_gpfs_status(result_payload, node_spec, thresholds):
    gpfs_mount_path = thresholds.get("gpfs_mount_path", "/gpfs/pvc")
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[GPFS] Command execution failed: {result_payload['error']}")

    output = result_payload['output'].strip()

    if output == 'not_mounted':
        return _create_failure(node_spec, TYPE_GPFS_STATUS, f"GPFS directory '{gpfs_mount_path}' is not mounted.")
    
    if output != 'mounted':
        return _create_failure(node_spec, TYPE_UNK, f"[GPFS] Unexpected output from check command: '{output}'")

    return _create_success([TYPE_GPFS_STATUS, TYPE_SHUTDOWN])