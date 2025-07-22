import paramiko
import re
from checker.core.model import (
    KEY_HOST, KEY_HOSTNAME, KEY_TYPE, KEY_EXTRA, KEY_SUCCESS, KEY_TYPES,
    TYPE_DISK_USAGE,
    TYPE_MEMORY_USAGE,    
    TYPE_HW_ERROR,
    TYPE_SSH,             
    TYPE_SHUTDOWN,       
    TYPE_UNK,            
)
from checker.utils.log import LOG
from checker.utils.host import check_host_online

import logbook

LOG = logbook.Logger(__name__)

# Helper functions for consistency
def _create_failure(host_info, type, extra):
    return {
        KEY_HOST: host_info[0], KEY_HOSTNAME: host_info[1],
        KEY_TYPE: type, KEY_EXTRA: extra, KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}


# --- 1. Disk Usage ---
def get_disk_usage_command():
    return "df -Ph / | tail -n 1"

def parse_disk_usage(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[Disk] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    try:
        parts = output.split()
        if len(parts) < 5:
            return _create_failure(host_info, TYPE_UNK, f"[Disk] Failed to parse df output: '{output}'")
        
        usage_percentage_str = parts[4].strip('%')
        usage_percentage = int(usage_percentage_str)

        if usage_percentage >= 85:
            extra = f"Root disk usage is at {usage_percentage}% (threshold >= 85%)."
            return _create_failure(host_info, TYPE_DISK_USAGE, extra)

    except (ValueError, IndexError) as e:
        return _create_failure(host_info, TYPE_UNK, f"[Disk] Could not parse percentage from '{output}'. Error: {e}")

    return _create_success([TYPE_DISK_USAGE, TYPE_SHUTDOWN])


# --- 2. Memory Usage ---
def get_memory_status_command():
    return "free -m | awk '/^Mem:/{printf(\"%.0f\", $3/$2 * 100)}'"

def parse_memory_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[Memory] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        usage_percent = int(output)
        if usage_percent >= 85:
            extra = f"Memory usage is at {usage_percent}% (threshold >= 85%)."
            return _create_failure(host_info, TYPE_MEMORY_USAGE, extra)

    except (ValueError, IndexError) as e:
        return _create_failure(host_info, TYPE_UNK, f"[Memory] Could not parse percentage from `free` output: '{output}'. Error: {e}")

    return _create_success([TYPE_MEMORY_USAGE, TYPE_SHUTDOWN])


# --- 3. Hardware Errors ---
def get_hardware_error_command():
    return "dmesg -T | grep -i 'Hardware error' | tail -n 20"

def parse_hardware_error(result_payload, host_info):
    if not result_payload['success']:
        LOG.debug(f"[{host_info[1]}] 'dmesg' command for HW Error check failed. Ignoring. Error: {result_payload['error']}")
        return _create_success([TYPE_HW_ERROR, TYPE_SHUTDOWN])

    output = result_payload['output']
    if output:
        extra = f"Recent hardware error detected in dmesg. Last few lines: {output}"
        return _create_failure(host_info, TYPE_HW_ERROR, extra)
        
    return _create_success([TYPE_HW_ERROR, TYPE_SHUTDOWN])
