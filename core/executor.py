import logbook
from checker.core.model import (
    KEY_HOST, KEY_HOSTNAME, KEY_TYPE, KEY_EXTRA, KEY_SUCCESS, KEY_TYPES, TYPE_UNK
)

LOG = logbook.Logger(__name__)

COMMAND_SEPARATOR = "---CHECKS-SPLITTER-7a8b9c1d2e3f4g5h---"

def execute_commands_and_parse(client, host_info, check_definitions):
    hostname = host_info[1]
    all_final_results = {}
    
    commands_to_execute = {}
    for check_name, (get_command_func, _) in check_definitions.items():
        cmd = get_command_func()
        if cmd:
            commands_to_execute[cmd] = check_name

    if not commands_to_execute:
        return {}

    shell_commands = [f"{cmd}; echo -n '{COMMAND_SEPARATOR}$?'" for cmd in commands_to_execute.keys()]
    super_command = " ; ".join(shell_commands)
    
    LOG.debug(f"[{hostname}] Executing super command: {super_command[:200]}...")

    try:
        stdin, stdout, stderr = client.exec_command(super_command, timeout=60)
        raw_output = stdout.read().decode('utf-8', errors='ignore')

        output_parts = raw_output.split(COMMAND_SEPARATOR)
    except Exception as e:
        LOG.error(f"[{hostname}] Super command execution failed: {e}", exc_info=True)

        for check_name in check_definitions:
            all_final_results[check_name] = {
                KEY_HOST: host_info[0], KEY_HOSTNAME: hostname,
                KEY_TYPE: TYPE_UNK, KEY_EXTRA: f"Command execution failed: {e}",
                KEY_SUCCESS: False
            }
        return all_final_results

    command_keys = list(commands_to_execute.keys())
    if len(output_parts) < len(command_keys):
         LOG.warning(f"[{hostname}] Output parts count ({len(output_parts)}) is less than command count ({len(command_keys)}). Output might be truncated.")

    command_results_map = {}
    for i, cmd in enumerate(command_keys):
        if i < len(output_parts):
            full_part = output_parts[i]
            exit_code_str = full_part[-1]
            real_output = full_part[:-1].strip()
            
            if exit_code_str != '0':
                err_output = stderr.read().decode('utf-8', errors='ignore')
                command_results_map[cmd] = {
                    'output': real_output,
                    'error': f"Command failed with exit code {exit_code_str}. Stderr might contain: {err_output[:200]}",
                    'success': False
                }
            else:
                command_results_map[cmd] = {'output': real_output, 'error': None, 'success': True}
        else:
            command_results_map[cmd] = {'output': '', 'error': 'No output received for this command.', 'success': False}

    for check_name, (get_command_func, parse_func) in check_definitions.items():
        cmd = get_command_func()
        if not cmd:
            continue
            
        result_payload = command_results_map.get(cmd)

        try:
            final_result = parse_func(result_payload, host_info)
            all_final_results[check_name] = final_result
        except Exception as e:
            LOG.error(f"[{hostname}] Parse function for '{check_name}' failed: {e}", exc_info=True)
            all_final_results[check_name] = {
                KEY_HOST: host_info[0], KEY_HOSTNAME: hostname,
                KEY_TYPE: TYPE_UNK, KEY_EXTRA: f"Parser crashed for {check_name}: {e}",
                KEY_SUCCESS: False
            }
            
    return all_final_results
