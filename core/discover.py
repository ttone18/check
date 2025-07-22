import paramiko
import logbook

LOG = logbook.Logger(__name__)

def _execute_simple_command(client: paramiko.SSHClient, command: str) -> str:
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=10)
        if stdout.channel.recv_exit_status() == 0:
            return stdout.read().decode().strip()
    except Exception:
        pass
    return ""

def discover_node_profile(client: paramiko.SSHClient, hostname: str) -> str:
    # 1. 尝试识别沐曦 GPU
    muxi_output = _execute_simple_command(client, "which mxgpu-smi")
    if "/bin/mxgpu-smi" in muxi_output:
        LOG.info(f"[{hostname}] Discovered Muxi GPU. Assigning profile: 'gpu_muxi_c100'")
        return "gpu_muxi_c100"

    # 2. 尝试识别 NVIDIA GPU
    nvidia_output = _execute_simple_command(client, "nvidia-smi -L")
    if nvidia_output:
        # 新增逻辑: 识别 4090
        if "GeForce RTX 4090" in nvidia_output:
            LOG.info(f"[{hostname}] Discovered NVIDIA 4090 GPU. Assigning profile: 'gpu_nvidia_4090'")
            return "gpu_nvidia_4090"
        # 默认是数据中心卡
        else:
            LOG.info(f"[{hostname}] Discovered NVIDIA Datacenter GPU. Assigning profile: 'nvidia'")
            return "nvidia"

    # 3. 如果都无法识别，则为未知
    LOG.warning(f"[{hostname}] Could not identify GPU type. Assigning profile: 'unknown'")
    return "unknown"

