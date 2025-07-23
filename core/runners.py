import logbook
import paramiko
import inspect

from checks import gpu_checks, system_checks, network_checks, storage_checks, muxi_checks
from core.model import *

LOG = logbook.Logger(__name__)

CHECK_REGISTRY = {
    # --- GPU Checks ---
    "gpu.count": (gpu_checks.get_gpu_count_command, gpu_checks.parse_gpu_count),
    "gpu.temperature": (gpu_checks.get_gpu_temp_command, gpu_checks.parse_gpu_temp),
    "gpu.thermal_slowdown": (gpu_checks.get_gpu_thermal_status_command, gpu_checks.parse_gpu_thermal_status),
    "gpu.ecc_soft_error": (gpu_checks.get_ecc_soft_uncorr_command, gpu_checks.parse_ecc_soft_uncorr),
    "gpu.xid_error": (gpu_checks.get_xid_command, gpu_checks.parse_xid),
    "gpu.nvlink_status": (gpu_checks.get_nvlink_status_command, gpu_checks.parse_nvlink_status),
    "gpu.pcie_status": (gpu_checks.get_pcie_limit_command, gpu_checks.parse_pcie_limit),
    "gpu.gdr_status": (gpu_checks.get_gdr_status_command, gpu_checks.parse_gdr_status),
    "gpu.acs_status": (gpu_checks.get_acs_status_command, gpu_checks.parse_acs_status),
    "gpu.fabric_manager_status": (gpu_checks.get_fabricmanager_status_command, gpu_checks.parse_fabricmanager_status),
    
    # --- System Checks ---
    "system.disk_usage": (system_checks.get_disk_usage_command, system_checks.parse_disk_usage),
    "system.memory_usage": (system_checks.get_memory_status_command, system_checks.parse_memory_status),
    "system.hw_error": (system_checks.get_hardware_error_command, system_checks.parse_hardware_error),
    
    # --- Network Checks ---
    "network.route": (network_checks.get_route_status_command, network_checks.parse_route_status),
    "network.ib_device_status": (network_checks.get_ibdev2netdev_status_command, network_checks.parse_ibdev2netdev_status),
    "network.ib_device_count": (network_checks.get_ibdev2netdev_count_command, network_checks.parse_ibdev2netdev_count),
    "network.ip_rule": (network_checks.get_ip_rule_count_command, network_checks.parse_ip_rule_count),

    # --- Storage Checks ---
    "storage.gpfs": (storage_checks.get_gpfs_status_command, storage_checks.parse_gpfs_status),

    # --- muxi Checks ---
    "gpu.muxi.count": (muxi_checks.get_muxi_gpu_count_command, muxi_checks.parse_muxi_gpu_count),
    "gpu.muxi.temperature": (muxi_checks.get_muxi_gpu_temp_command, muxi_checks.parse_muxi_gpu_temp),
    "gpu.muxi.ecc_state": (muxi_checks.get_muxi_ecc_state_command, muxi_checks.parse_muxi_ecc_state),
    "gpu.muxi.pcie_status": (muxi_checks.get_muxi_pcie_status_command, muxi_checks.parse_muxi_pcie_status)
    # 宁夏muxi不支持 mx-smi --show-clk-tr，可注释
    "gpu.muxi.thermal_status" : (muxi_checks.get_muxi_thermal_status_command, muxi_checks.parse_muxi_thermal_status)
    "network.muxi.metaxlink_status": (muxi_checks.get_muxi_metaxlink_status_command, muxi_checks.parse_muxi_metaxlink_status)
}

def _execute_ssh_command(client: paramiko.SSHClient, command: str, timeout=15) -> dict:
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode('utf-8', errors='ignore')
        error = stderr.read().decode('utf-8', errors='ignore')

        if exit_code == 0:
            return {'success': True, 'output': output}
        else:
            err_msg = f"ExitCode:{exit_code}, Stderr:'{error.strip()}', Stdout:'{output.strip()}'"
            return {'success': False, 'error': err_msg}
    except Exception as e:
        return {'success': False, 'error': f"Command execution exception: {e}"}

def run_specific_checks(client: paramiko.SSHClient, node_spec: dict, thresholds: dict, checks_to_run: list) -> dict:
    all_results = {}
    hostname = node_spec.get('hostname', node_spec.get('host'))

    for check_name in checks_to_run:
        if check_name not in CHECK_REGISTRY:
            LOG.warning(f"[{hostname}] Check '{check_name}' is not defined in CHECK_REGISTRY. Skipping.")
            continue
        
        get_command_func, parse_result_func = CHECK_REGISTRY[check_name]

        command = ""
        sig = inspect.signature(get_command_func)
        if len(sig.parameters) > 0:
            command = get_command_func(thresholds)
        else:
            command = get_command_func()
        
        LOG.debug(f"[{hostname}] Executing check '{check_name}': {command}")
        result_payload = _execute_ssh_command(client, command)
        
        final_result = parse_result_func(result_payload, node_spec, thresholds)
        
        all_results[check_name] = final_result

    return all_results

