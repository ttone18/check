import paramiko
import socket
from checker.core.model import (
    KEY_HOST, KEY_HOSTNAME, KEY_TYPE, KEY_EXTRA, KEY_SUCCESS, KEY_TYPES,
    TYPE_ROUTE,
    TYPE_IBDEV,         
    TYPE_IBDEV_CNT,     
    TYPE_IP_RULE,
    TYPE_SSH,          
    TYPE_SHUTDOWN,      
    TYPE_UNK,
)

from checker.utils.log import LOG
from checker.utils.host import check_host_online

import logbook

LOG = logbook.Logger(__name__)

EXPECTED_IBDEV_COUNT = 8
EXPECTED_IP_RULE_COUNT = 19

def _create_failure(host_info, type, extra):
    return {
        KEY_HOST: host_info[0], KEY_HOSTNAME: host_info[1],
        KEY_TYPE: type, KEY_EXTRA: extra, KEY_SUCCESS: False
    }

def _create_success(types):
    return {KEY_TYPES: types, KEY_SUCCESS: True}


# --- 1. Route Status (N+1 query problem solved) ---
def get_route_status_command():
    shell_script = """
    for table in $(ip rule list | grep -i 'static' | awk '{for(i=1;i<=NF;i++) if($i=="lookup") print $(i+1)}'); do
        if [ -z "$(ip route show table $table)" ]; then
            echo "$table"
        fi
    done
    """
    return shell_script

def parse_route_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[Route] Command execution failed: {result_payload['error']}")

    output = result_payload['output'].strip()
    if output:
        empty_tables = output.split(' ')
        extra = f"Found empty static route tables: {', '.join(empty_tables)}"
        return _create_failure(host_info, TYPE_ROUTE, extra)
    
    return _create_success([TYPE_ROUTE, TYPE_IP_RULE, TYPE_SHUTDOWN])


# --- 2. InfiniBand Device Status ---
def get_ibdev2netdev_status_command():
    return "ibdev2netdev -v | grep -i 'link_state: down'"

def parse_ibdev2netdev_status(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[IB Status] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output'].strip()
    if output:
        extra = f"One or more InfiniBand devices are down: {output}"
        return _create_failure(host_info, TYPE_IBDEV, extra)

    return _create_success([TYPE_IBDEV, TYPE_SHUTDOWN])


# --- 3. InfiniBand Device Count ---
def get_ibdev2netdev_count_command():
    return "ibdev2netdev | wc -l"

def parse_ibdev2netdev_count(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[IB Count] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        dev_count = int(output.strip())
        if dev_count != EXPECTED_IBDEV_COUNT:
            extra = f'Expected {EXPECTED_IBDEV_COUNT} IB devices, but found {dev_count}.'
            return _create_failure(host_info, TYPE_IBDEV_CNT, extra)
    except (ValueError, IndexError):
        return _create_failure(host_info, TYPE_UNK, f"[IB Count] Failed to parse count from output: '{output}'")
    
    return _create_success([TYPE_IBDEV_CNT, TYPE_SHUTDOWN])


# --- 4. IP Rule Count ---
def get_ip_rule_count_command():
    return "ip rule list | wc -l"

def parse_ip_rule_count(result_payload, host_info):
    if not result_payload['success']:
        return _create_failure(host_info, TYPE_UNK, f"[IP Rule] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    try:
        rule_count = int(output.strip())
        if rule_count != EXPECTED_IP_RULE_COUNT:
            extra = f'Expected {EXPECTED_IP_RULE_COUNT} IP rules, but found {rule_count}.'
            return _create_failure(host_info, TYPE_IP_RULE, extra)
    except (ValueError, IndexError):
        return _create_failure(host_info, TYPE_UNK, f"[IP Rule] Failed to parse count from output: '{output}'")
    
    return _create_success([TYPE_IP_RULE, TYPE_SHUTDOWN])