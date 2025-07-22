import logbook

from core.models import (
    KEY_HOST, KEY_HOSTNAME, KEY_TYPE, KEY_EXTRA, KEY_SUCCESS, KEY_TYPES, TYPE_UNK,
    TYPE_MUXI_SMI_CMD_ERROR, TYPE_MUXI_GPU_CNT, TYPE_MUXI_GPU_TEMP,
    TYPE_MUXI_ECC_STATE, TYPE_MUXI_PCIE_STATUS, TYPE_MUXI_THERMAL_STATUS,
    TYPE_MUXI_METAXLINK_STATUS
)

LOG = logbook.Logger(__name__)

def _create_failure(host_info, type, extra):
    return {
        KEY_HOST: host_info[0], KEY_HOSTNAME: host_info[1],
        KEY_TYPE: type, KEY_EXTRA: extra, KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}

# --- 1. Muxi GPU Count ---
def get_muxi_gpu_count_command():
    return "mxgpu-smi -L | wc -l"

def parse_muxi_gpu_count(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"Command to get Muxi GPU count failed: {result_payload['error']}")

    output = result_payload['output']
    expected_count = 8
    try:
        gpu_count = int(output.strip())
        if gpu_count != expected_count:
            return _create_failure(host_info, TYPE_MUXI_GPU_CNT, f'Expected {expected_count} Muxi GPUs, but found {gpu_count}.')
    except ValueError:
        return _create_failure(host_info, TYPE_UNK, f"Could not parse Muxi GPU count from output: '{output}'")
        
    return _create_success([TYPE_MUXI_GPU_CNT, TYPE_MUXI_SMI_CMD_ERROR])

# --- 2. Muxi GPU Temperature ---
def get_muxi_gpu_temp_command():
    
    return "mxgpu-smi --query-gpu=temperature.gpu --format=csv,noheader"

def parse_muxi_gpu_temp(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"Command to get Muxi GPU temperature failed: {result_payload['error']}")

    output = result_payload['output']
    problematic_gpus = []
    threshold = 85
    
    try:
        lines = output.strip().split(' ')
        for i, line in enumerate(lines):
            if not line: continue
            temp = int(line.strip())
            if temp > threshold:
                problematic_gpus.append(f"GPU-{i} at {temp}C")

        if problematic_gpus:
            extra = f"Muxi GPU temperature over {threshold}C: {'; '.join(problematic_gpus)}"
            return _create_failure(host_info, TYPE_MUXI_GPU_TEMP, extra)
            
    except (ValueError, IndexError) as e:
        return _create_failure(host_info, TYPE_UNK, f"Failed to parse Muxi GPU temperature. Error: {e}. Output: '{output[:100]}'")

    return _create_success([TYPE_MUXI_GPU_TEMP, TYPE_MUXI_SMI_CMD_ERROR])

# --- 3. Muxi ECC State ---
def get_muxi_ecc_state_command():
    return "mxgpu-smi -q -d ECC"

def parse_muxi_ecc_state(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"Command for Muxi ECC state failed: {result_payload['error']}")
    
    output = result_payload['output']
    errors_found = []

    for line in output.strip().split(' '):
        if "Errors" in line and " 0" not in line:
             errors_found.append(line.strip())

    if errors_found:
        return _create_failure(host_info, TYPE_MUXI_ECC_STATE, f"Muxi ECC errors detected: {'; '.join(errors_found)}")

    return _create_success([TYPE_MUXI_ECC_STATE])

# --- 4. Muxi PCIe Link Status ---
def get_muxi_pcie_status_command():
    return "mxgpu-smi --query-gpu=pci.link.gen.current,pci.link.gen.max,pci.link.width.current,pci.link.width.max --format=csv,noheader"

def parse_muxi_pcie_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"[PCIe] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    degraded_gpus = []

    try:
        lines = output.strip().split(' ')
        for i, line in enumerate(lines):
            if not line: continue
            parts = [p.strip() for p in line.split(',')]
            gen_curr, gen_max, width_curr, width_max = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
            
            if gen_curr < gen_max or width_curr < width_max:
                degraded_gpus.append(f"GPU-{i} degraded (Gen:{gen_curr}/{gen_max}, Width:x{width_curr}/x{width_max})")

        if degraded_gpus:
            return _create_failure(host_info, TYPE_MUXI_PCIE_STATUS, f"Muxi PCIe link degradation detected: {'; '.join(degraded_gpus)}")

    except (ValueError, IndexError) as e:
        return _create_failure(host_info, TYPE_UNK, f"[PCIe] Failed to parse Muxi PCIe status. Error: {e}. Output: '{output[:100]}'")

    return _create_success([TYPE_MUXI_PCIE_STATUS])

# --- 5. Muxi Thermal Status (Throttling) ---
def get_muxi_thermal_status_command():
    return "mxgpu-smi -q -d PERFORMANCE"

def parse_muxi_thermal_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"[Thermal] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    throttling_lines = []
    
    for line in output.strip().split('\n'):
        if "Throttle" in line or "Slowdown" in line:
            if "Not Active" not in line and "None" not in line:
                throttling_lines.append(line.strip())
            
    if throttling_lines:
        extra = f"Muxi GPU Thermal Slowdown detected: {'; '.join(throttling_lines)}"
        return _create_failure(host_info, TYPE_MUXI_THERMAL_STATUS, extra)

    return _create_success([TYPE_MUXI_THERMAL_STATUS])

# --- 6. Muxi MetaXLink Status ---
def get_muxi_metaxlink_status_command():
    return "mxgpu-smi metaxlink -s"

def parse_muxi_metaxlink_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_MUXI_SMI_CMD_ERROR, f"[MetaXLink] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    inactive_links = []
    
    for line in output.strip().split(' '):
        if "Link" in line and "Active" not in line and "UP" not in line:
            inactive_links.append(line.strip())

    if inactive_links:
        return _create_failure(host_info, TYPE_MUXI_METAXLINK_STATUS, f"Muxi MetaXLink inactive links found: {'; '.join(inactive_links)}")

    return _create_success([TYPE_MUXI_METAXLINK_STATUS])
