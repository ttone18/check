KEY_HOST = 'host'
KEY_HOSTNAME = 'hostname'
KEY_TYPE = 'type'
KEY_EXTRA = 'extra'
KEY_SUCCESS = 'success'
KEY_TYPES = 'types'

TABLE_NAME = 'gpu_monitoring_status'
MAX_RETRIES = 3
RETRY_INTERVAL = 5
EVENTS_ALARMS = 'events_alarms'
TABLE_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `gpu_monitoring_status` (
  `id` INT AUTO_INCREMENT PRIMARY KEY,
  `hostname` VARCHAR(255) NOT NULL COMMENT '节点主机名',
  `check_id` VARCHAR(255) NOT NULL COMMENT '唯一的检查项ID, 例如: gpu_0_temp',
  `status` VARCHAR(50) NOT NULL COMMENT '当前状态 (e.g., OK, PROBLEM)',
  `message` TEXT COMMENT '告警或恢复的详细信息',
  `first_occurrence` TIMESTAMP NULL COMMENT '问题首次发生时间',
  `last_update` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录最后更新时间',
  UNIQUE KEY `idx_host_check` (`hostname`, `check_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

EVENTS_ALARMS_CREATE_SQL = ""

TYPE_LINE_ERROR = 'gpu_error'
TYPE_SMI_CMD = 'smi_cmd'
TYPE_GPU_HIGH_TEMP = 'gpu_high_temp'

# --- System & Server ---
TYPE_UNK = 'unk'
TYPE_SSH = "system.ssh"
TYPE_SHUTDOWN = "system.shutdown"
TYPE_DISK_USAGE = "system.disk_usage"
TYPE_MEMORY_USAGE = "system.memory_usage"
TYPE_HW_ERROR = "system.hw_error"

# --- Network ---
TYPE_ROUTE = "network.route"
TYPE_IBDEV = "network.ib_device_status"
TYPE_IBDEV_CNT = "network.ib_device_count"
TYPE_IP_RULE = "network.ip_rule"
TYPE_TRAFFIC = "network.traffic"

# --- GPU ---
TYPE_GPU_CNT = "gpu.count"
TYPE_GPU_TEMP = "gpu.temperature"
TYPE_ECC_SOFT = "gpu.ecc_soft_error"
TYPE_PCIE = "gpu.pcie_status"
TYPE_NVLINK = "gpu.nvlink_status"
TYPE_GDR = "gpu.gdr_status"
TYPE_FM = "gpu.fabric_manager_status"
TYPE_ACS = "gpu.acs_status"
TYPE_GPU_THERMAL_SLOWDOWN = "gpu.thermal_slowdown"
TYPE_XID_INFO = "gpu.xid_info"
TYPE_XID_ERROR = "gpu.xid_error"
TYPE_SMI_CMD_ERROR = "gpu.smi_cmd_error"

# --- Storage ---
TYPE_GPFS_STATUS = "storage.gpfs"

# --- GPU - Muxi ---
TYPE_MUXI_SMI_CMD_ERROR = "gpu.muxi.smi_cmd_error"
TYPE_MUXI_GPU_CNT = "gpu.muxi.count"
TYPE_MUXI_GPU_TEMP = "gpu.muxi.temperature"
TYPE_MUXI_ECC_STATE = "gpu.muxi.ecc_state"
TYPE_MUXI_PCIE_STATUS = "gpu.muxi.pcie_status"
TYPE_MUXI_THERMAL_STATUS = "gpu.muxi.thermal_status"
TYPE_MUXI_METAXLINK_STATUS = "network.muxi.metaxlink_status"

P0, P1, P2, P3 = "P0 - 紧急", "P1 - 高", "P2 - 中", "P3 - 低"

# 定义告警群组常量
GROUP_HARDWARE = "hardware_group" 
GROUP_SOFTWARE = "software_group" 
GROUP_ANALYTICS = "analytics_group" 

ALERT_METADATA = {
    # P1
    TYPE_SSH:       {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点SSH登录失败"},
    TYPE_IBDEV:     {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点网卡端口Down"},
    TYPE_GPU_CNT:       {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点GPU数量与预期不符"},
    TYPE_ECC_SOFT:      {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点GPU发生ECC错误"},
    TYPE_SMI_CMD_ERROR: {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点nvidia-smi命令卡死或报错"},
    TYPE_IBDEV_CNT: {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点网卡数量检查失败"},
    TYPE_GPU_HIGH_TEMP: {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点GPU温度严重超标(>85C)"},
    TYPE_XID_ERROR:     {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点出现严重XID错误 (如XID 79)"},
    TYPE_SHUTDOWN:  {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点实例失联 (无法Ping通)"},
    TYPE_HW_ERROR:  {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点发生硬件错误"},
    TYPE_NVLINK:        {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点NVLink链路状态异常"},
    TYPE_MUXI_PCIE_STATUS:   {'priority': P1, 'group': GROUP_HARDWARE, 'title': "节点沐曦GPU的PCIE链路降级"}, 

    # P2
    TYPE_PCIE:      {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点网卡PCIE链路降级"},
    TYPE_DISK_USAGE:    {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点存储使用量超80%"},
    TYPE_MEMORY_USAGE:  {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点内存使用量超80%"},
    TYPE_GPU_TEMP:      {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点GPU温度超标(80C-85C)"},
    TYPE_ACS:           {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点PCIE ACS状态异常"}, 
    TYPE_FM:            {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点Fabric Manager服务异常"},
    TYPE_GDR:           {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点GPUDirect RDMA (GDR)异常"},
    TYPE_GPFS_STATUS:   {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点GPFS挂载状态异常"},
    TYPE_ROUTE:         {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点路由状态异常"},
    TYPE_LINE_ERROR:    {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点检查命令返回行错误"},
    TYPE_UNK:           {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "发生未知检查错误"},
    TYPE_MUXI_SMI_CMD_ERROR: {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点mxgpu-smi命令卡死或报错"},
    TYPE_MUXI_GPU_CNT:       {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点沐曦GPU数量与预期不符"},
    TYPE_MUXI_GPU_TEMP:      {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点沐曦GPU温度超标"},
    TYPE_MUXI_ECC_STATE:     {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点沐曦GPU发生ECC错误"},
    TYPE_MUXI_METAXLINK_STATUS: {'priority': P2, 'group': GROUP_SOFTWARE, 'title': "节点沐曦MetaXLink链路状态异常"},

    # P3
    TYPE_TRAFFIC:              {'priority': P3, 'group': GROUP_ANALYTICS, 'title': "节点网络流量超阈值记录"},
    TYPE_GPU_THERMAL_SLOWDOWN: {'priority': P3, 'group': GROUP_ANALYTICS, 'title': "节点GPU出现降频 (记录)"},
    TYPE_XID_INFO:             {'priority': P3, 'group': GROUP_ANALYTICS, 'title': "节点出现非关键XID错误 (记录)"},
    TYPE_IP_RULE:              {'priority': P3, 'group': GROUP_ANALYTICS, 'title': "节点IP规则检查异常 (记录)"},
    TYPE_MUXI_THERMAL_STATUS:   {'priority': P3, 'group': GROUP_ANALYTICS, 'title': "节点沐曦GPU出现过热状态 (记录)"},
}