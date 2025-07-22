import yaml
from .logging import LOG

def load_all_configs(
    nodes_path='configs/nodes.yaml', 
    profiles_path='configs/profiles.yaml', 
    reporters_path='configs/reporters.yaml'
):
    try:
        with open(nodes_path, 'r') as f:
            nodes_config = yaml.safe_load(f) or {}
        with open(profiles_path, 'r') as f:
            profiles_config = yaml.safe_load(f) or {}
        with open(reporters_path, 'r') as f:
            reporters_config = yaml.safe_load(f) or {}
            
    except FileNotFoundError as e:
        LOG.error(f"Config file not found: {e}. Exiting.")
        return None
    except Exception as e:
        LOG.error(f"Error parsing YAML files: {e}. Exiting.")
        return None

    all_configs = {
        'nodes': nodes_config.get('nodes', []),
        'profiles': profiles_config.get('profiles', {}),
        'reporters': reporters_config.get('reporters', {})
    }
    
    LOG.info(f"Successfully loaded {len(all_configs['nodes'])} nodes, "
             f"{len(all_configs['profiles'])} profiles, "
             f"and {len(all_configs['reporters'])} reporters.")
             
    return all_configs
