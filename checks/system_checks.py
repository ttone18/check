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


# --- 1. Disk Usage ---
def get_disk_usage_command():
    return "df -Ph / | tail -n 1"

def parse_disk_usage(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[Disk] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    try:
        parts = output.split()
        if len(parts) < 5:
            return _create_failure(node_spec, TYPE_UNK, f"[Disk] Failed to parse df output: '{output}'")
        
        usage_percentage_str = parts[4].strip('%')
        usage_percentage = int(usage_percentage_str)

        if usage_percentage >= thresholds.get("disk_usage_percent", 85):
            extra = f"Root disk usage is at {usage_percentage}% (threshold >= 85%)."
            return _create_failure(node_spec, TYPE_DISK_USAGE, extra)

    except (ValueError, IndexError) as e:
        return _create_failure(node_spec, TYPE_UNK, f"[Disk] Could not parse percentage from '{output}'. Error: {e}")

    return _create_success([TYPE_DISK_USAGE, TYPE_SHUTDOWN])


# --- 2. Memory Usage ---
def get_memory_status_command():
    return "free -m | awk '/^Mem:/{printf(\"%.0f\", $3/$2 * 100)}'"

def parse_memory_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[Memory] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        usage_percent = int(output)
        if usage_percent >= thresholds.get("memory_usage_percent", 85):
            extra = f"Memory usage is at {usage_percent}% (threshold >= 85%)."
            return _create_failure(node_spec, TYPE_MEMORY_USAGE, extra)

    except (ValueError, IndexError) as e:
        return _create_failure(node_spec, TYPE_UNK, f"[Memory] Could not parse percentage from `free` output: '{output}'. Error: {e}")

    return _create_success([TYPE_MEMORY_USAGE, TYPE_SHUTDOWN])


# --- 3. Hardware Errors ---
def get_hardware_error_command():
    return "dmesg -T | grep -i 'Hardware error' | tail -n 20"

def parse_hardware_error(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        hostname = node_spec.get('hostname', 'Unknown-Host')
        LOG.debug(f"[{hostname}] 'dmesg' command for HW Error check failed. Ignoring. Error: {result_payload['error']}")
        return _create_success([TYPE_HW_ERROR, TYPE_SHUTDOWN])

    output = result_payload['output']
    if output:
        extra = f"Recent hardware error detected in dmesg. Last few lines: {output}"
        return _create_failure(node_spec, TYPE_HW_ERROR, extra)
        
    return _create_success([TYPE_HW_ERROR, TYPE_SHUTDOWN])
