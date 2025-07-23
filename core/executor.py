import logbook
import paramiko

from core.config import load_all_configs
from discover import discover_node_profile
import runners

LOG = logbook.Logger(__name__)


def run_health_checks_on_node(client: paramiko.SSHClient, host_info: dict):
    hostname = host_info.get('hostname', host_info.get('host'))
    LOG.info(f"[{hostname}] Starting health check orchestration...")

    try:
        configs = load_all_configs()
        thresholds = configs.get('thresholds', {})
        profiles = configs.get('profiles', {})
        LOG.debug(f"[{hostname}] Configurations loaded successfully.")
    except Exception as e:
        LOG.critical(f"[{hostname}] CRITICAL FAILURE: Could not load configurations. Error: {e}")
        return {
            "config.load": {
                "success": False,
                "type": "CONFIG_ERROR",
                "extra": f"Failed to load configurations: {e}"
            }
        }
    
    try:
        profile_name = discover_node_profile(client, hostname)
    except Exception as e:
        LOG.error(f"[{hostname}] Node discovery failed: {e}", exc_info=True)
        return {
            "discover.profile": {
                "success": False,
                "type": "DISCOVERY_ERROR",
                "extra": f"Failed during node profile discovery: {e}"
            }
        }
    
    checks_to_run = profiles.get(profile_name, [])
    if not checks_to_run:
        LOG.warning(f"[{hostname}] No checks defined for profile '{profile_name}'. Nothing to do.")
        return {}
    
    LOG.info(f"[{hostname}] Node identified with profile '{profile_name}'. Running {len(checks_to_run)} checks.")

    try:
        results = runners.run_specific_checks(
            client=client,
            node_spec=host_info,      # Passing the whole dict now
            thresholds=thresholds,    # Passing the thresholds dict
            checks_to_run=checks_to_run
        )
        LOG.info(f"[{hostname}] Health checks completed.")
        return results
    except Exception as e:
        LOG.critical(f"[{hostname}] A critical unhandled error occurred in the runner: {e}", exc_info=True)
        return {
            "runner.execution": {
                "success": False,
                "type": "RUNNER_CRASH",
                "extra": f"The runner module crashed unexpectedly: {e}"
            }
        }
