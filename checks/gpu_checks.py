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

def _parse_numeric_list(result_payload, node_spec, issue_type, threshold, check_name):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_SMI_CMD_ERROR, f"[{check_name}] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    problematic_gpus = []
    
    try:
        lines = output.strip().splitlines()
        for i, line in enumerate(lines):
            if not line: continue
            value = int(line.strip())
            if value > threshold:
                problematic_gpus.append(f"GPU-{i} value is {value}")
        
        if problematic_gpus:
            extra = f"[{check_name}] Found {len(problematic_gpus)} GPU(s) over threshold > {threshold}. Details: {'; '.join(problematic_gpus)}"
            return _create_failure(node_spec, issue_type, extra)
            
    except (ValueError, IndexError) as e:
        return _create_failure(node_spec, TYPE_UNK, f"[{check_name}] Failed to parse output. Error: {e}. Output: '{output[:100]}'")

    return _create_success([issue_type, TYPE_SMI_CMD_ERROR])

# --- 1. GPU Count ---
def get_gpu_count_command():
    return "nvidia-smi --query-gpu=gpu_uuid --format=csv,noheader | wc -l"

def parse_gpu_count(result_payload, node_spec, thresholds):
    expected_count = thresholds.get("gpu_count", 8)
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_SMI_CMD_ERROR, f"Command to get GPU count failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        gpu_count = int(output.strip())
        if gpu_count != expected_count:
            return _create_failure(node_spec, TYPE_GPU_CNT, f'Expected 8 GPUs, but found {gpu_count}.')
    except ValueError:
        return _create_failure(node_spec, TYPE_UNK, f"Could not parse GPU count from output: '{output}'")
        
    return _create_success([TYPE_GPU_CNT, TYPE_SMI_CMD_ERROR])

# --- 2. GPU Temperature ---
def get_gpu_temp_command():
    return "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader"

def parse_gpu_temp(result_payload, node_spec, thresholds):
    temp_threshold = thresholds.get("gpu_temp", 80)
    high_temp_threshold = thresholds.get("gpu_high_temp", 85)
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_SMI_CMD_ERROR, f"Command to get GPU temperature failed: {result_payload['error']}")

    output = result_payload['output']
    high_temp_gpus = [] # > 85C (P1)
    warn_temp_gpus = [] # 80-85C (P2)
    
    try:
        lines = output.strip().splitlines()
        for i, line in enumerate(lines):
            if not line: continue
            temp = int(line.strip())
            if temp > high_temp_threshold:
                high_temp_gpus.append(f"GPU-{i} at {temp}C")
            elif temp > temp_threshold:
                warn_temp_gpus.append(f"GPU-{i} at {temp}C")

        if high_temp_gpus:
            extra = f"Critical temperature detected: {'; '.join(high_temp_gpus)}"
            return _create_failure(node_spec, TYPE_GPU_HIGH_TEMP, extra)
        if warn_temp_gpus:
            extra = f"Warning temperature detected: {'; '.join(warn_temp_gpus)}"
            return _create_failure(node_spec, TYPE_GPU_TEMP, extra)
            
    except (ValueError, IndexError) as e:
        return _create_failure(node_spec, TYPE_UNK, f"Failed to parse GPU temperature output. Error: {e}. Output: '{output[:100]}'")

    return _create_success([TYPE_GPU_HIGH_TEMP, TYPE_GPU_TEMP, TYPE_SMI_CMD_ERROR])

# --- 3. XID Errors ---
def get_xid_command():
    return "dmesg -T | grep -i xid | tail -n 20"

def parse_xid(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        hostname = node_spec.get('hostname', node_spec.get('host'))
        LOG.debug(f"[{hostname}] 'dmesg' command ...")
        return _create_success([TYPE_XID_ERROR, TYPE_XID_INFO])

    output = result_payload['output']
    if not output:
        return _create_success([TYPE_XID_ERROR, TYPE_XID_INFO])

    critical_xid_list = ["79"] 
    is_critical = any(f"Xid: {code}" in output for code in critical_xid_list)
    
    if is_critical:
        return _create_failure(node_spec, TYPE_XID_ERROR, f"Critical XID error found. Recent logs: {output}")
    else:
        return _create_failure(node_spec, TYPE_XID_INFO, f"Non-critical XID error found (P3). Recent logs: {output}")

# --- 4. ECC Soft Uncorrected Errors ---
def get_ecc_soft_uncorr_command():
    return "nvidia-smi --query-gpu=ecc.errors.uncorrected.volatile.total --format=csv,noheader"

def parse_ecc_soft_uncorr(result_payload, node_spec, thresholds):
    return _parse_numeric_list(result_payload, node_spec, TYPE_ECC_SOFT, 0, "ECC Soft Uncorr")

# --- 5. PCIe Link Status ---
def get_pcie_limit_command():
    shell_script = """
    for dev_pci_addr in $(ibdev2netdev -v | grep 'ConnectX-7' | awk '{print $1}'); do
      status=$(lspci -vv -s "$dev_pci_addr" | grep 'LnkSta:');
      capability=$(lspci -vv -s "$dev_pci_addr" | grep 'LnkCap:');
      
      # Extract speed and width from status and capability
      status_speed=$(echo "$status" | awk -F',|:' '{print $2}' | sed 's/Speed //g;s/GT.*//g' | xargs);
      status_width=$(echo "$status" | awk -F',|:' '{print $3}' | sed 's/Width //g' | xargs);
      cap_speed=$(echo "$capability" | awk -F',|:' '{print $2}' | sed 's/Speed //g;s/GT.*//g' | xargs);
      cap_width=$(echo "$capability" | awk -F',|:' '{print $3}' | sed 's/Width //g' | xargs);

      # Use floating point comparison for speed
      if [ $(echo "$status_speed < $cap_speed" | bc) -ne 0 ] || [ "$status_width" != "$cap_width" ]; then
        echo "DEGRADED: Device $dev_pci_addr. Capability:[$capability], Current Status:[$status]";
      fi
    done
    """
    return shell_script

def parse_pcie_limit(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[PCIe] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    if output: 
        return _create_failure(node_spec, TYPE_PCIE, f"PCIe link degradation detected: {output}")

    return _create_success([TYPE_PCIE])

# --- 6. NVLink Status ---
def get_nvlink_status_command():
    return "lspci | grep -i 'nvidia' | grep -c 'bridge'"

def parse_nvlink_status(result_payload, node_spec, thresholds):
    expected_bridges = thresholds.get("nvlink_bridge_count", 4)
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[NVLink] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        bridge_count = int(output.strip())
        if bridge_count != expected_bridges:
            return _create_failure(node_spec, TYPE_NVLINK, f'Expected 4 NVIDIA bridges, but found {bridge_count}.')
    except ValueError:
        return _create_failure(node_spec, TYPE_UNK, f"[NVLink] Could not parse bridge count from output: '{output}'")

    return _create_success([TYPE_NVLINK])

# --- 7. GDR (GPUDirect RDMA) Status ---
def get_gdr_status_command():
    return "lsmod | grep -c 'nv_peer_mem'"

def parse_gdr_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[GDR] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        module_count = int(output.strip())
        if module_count == 0:
            return _create_failure(node_spec, TYPE_GDR, 'GPUDirect RDMA module (nv_peer_mem) is not loaded.')
    except ValueError:
        return _create_failure(node_spec, TYPE_UNK, f"[GDR] Could not parse lsmod output: '{output}'")

    return _create_success([TYPE_GDR])

# --- 8. Fabric Manager Status ---
def get_fabricmanager_status_command():
    return "systemctl is-active nvidia-fabricmanager.service"

def parse_fabricmanager_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        hostname = node_spec.get('hostname', node_spec.get('host'))
        LOG.debug(f"[{hostname}] Fabric Manager check failed (likely not installed): {result_payload['error']}")
        return _create_success([TYPE_FM])

    output = result_payload['output'].strip()
    if output != "active":
        return _create_failure(node_spec, TYPE_FM, f'NVIDIA Fabric Manager service is not active. Current state: {output}.')

    return _create_success([TYPE_FM])

# --- 9. ACS (Access Control Services) Status ---
def get_acs_status_command():
    return "lspci -vvv | grep ACSCtl | grep 'SrcValid+'"

def parse_acs_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[ACS] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    if output:
        return _create_failure(node_spec, TYPE_ACS, f'ACS validation is improperly enabled on one or more devices: {output}')

    return _create_success([TYPE_ACS])

# --- 10. GPU Thermal Slowdown ---
def get_gpu_thermal_status_command():
    return "nvidia-smi -q | grep 'Thermal Slowdown'"

def parse_gpu_thermal_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_SMI_CMD_ERROR, f"[Thermal] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    problematic_lines = []
    
    for line in output.strip().splitlines():
        if 'Not Active' not in line:
            problematic_lines.append(line.strip())
            
    if problematic_lines:
        extra = f"GPU Thermal Slowdown detected: {'; '.join(problematic_lines)}"
        return _create_failure(node_spec, TYPE_GPU_THERMAL_SLOWDOWN, extra)

    return _create_success([TYPE_GPU_THERMAL_SLOWDOWN])