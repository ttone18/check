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

def parse_route_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[Route] Command execution failed: {result_payload['error']}")

    output = result_payload['output'].strip()
    if output:
        empty_tables = output.splitlines() 
        extra = f"Found empty static route tables: {', '.join(empty_tables)}"
        return _create_failure(node_spec, TYPE_ROUTE, extra)
    
    return _create_success([TYPE_ROUTE, TYPE_IP_RULE, TYPE_SHUTDOWN])


# --- 2. InfiniBand Device Status ---
def get_ibdev2netdev_status_command():
    return "ibdev2netdev -v | grep -i 'link_state: down'"

def parse_ibdev2netdev_status(result_payload, node_spec, thresholds):
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[IB Status] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output'].strip()
    if output:
        extra = f"One or more InfiniBand devices are down: {output}"
        return _create_failure(node_spec, TYPE_IBDEV, extra)

    return _create_success([TYPE_IBDEV, TYPE_SHUTDOWN])


# --- 3. InfiniBand Device Count ---
def get_ibdev2netdev_count_command():
    return "ibdev2netdev | wc -l"

def parse_ibdev2netdev_count(result_payload, node_spec, thresholds):
    expected_ibdev_count = thresholds.get("expected_ibdev_count", 8)
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[IB Count] Command execution failed: {result_payload['error']}")
    
    output = result_payload['output']
    try:
        dev_count = int(output.strip())
        if dev_count != expected_ibdev_count:
            extra = f'Expected {expected_ibdev_count} IB devices, but found {dev_count}.'
            return _create_failure(node_spec, TYPE_IBDEV_CNT, extra)
    except (ValueError, IndexError):
        return _create_failure(node_spec, TYPE_UNK, f"[IB Count] Failed to parse count from output: '{output}'")
    
    return _create_success([TYPE_IBDEV_CNT, TYPE_SHUTDOWN])


# --- 4. IP Rule Count ---
def get_ip_rule_count_command():
    return "ip rule list | wc -l"

def parse_ip_rule_count(result_payload, node_spec, thresholds):
    expected_ip_rule_count = thresholds.get("expected_ip_rule_count", 19)
    if not result_payload['success']:
        return _create_failure(node_spec, TYPE_UNK, f"[IP Rule] Command execution failed: {result_payload['error']}")

    output = result_payload['output']
    try:
        rule_count = int(output.strip())
        if rule_count != expected_ip_rule_count:
            extra = f'Expected {expected_ip_rule_count} IP rules, but found {rule_count}.'
            return _create_failure(node_spec, TYPE_IP_RULE, extra)
    except (ValueError, IndexError):
        return _create_failure(node_spec, TYPE_UNK, f"[IP Rule] Failed to parse count from output: '{output}'")
    
    return _create_success([TYPE_IP_RULE, TYPE_SHUTDOWN])