import yaml
import logbook
import os

LOG = logbook.Logger("ConfigLoader")

CONFIG_DIR = 'configs'
APP_CONFIG_PATH = os.path.join(CONFIG_DIR, 'app_config.yaml')
NODES_CONFIG_PATH = os.path.join(CONFIG_DIR, 'nodes.yaml')
PROFILES_CONFIG_PATH = os.path.join(CONFIG_DIR, 'profiles.yaml')
THRESHOLDS_CONFIG_PATH = os.path.join(CONFIG_DIR, 'thresholds.yaml')

def _load_yaml_file(path, default_value=None):
    if default_value is None:
        default_value = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or default_value
    except FileNotFoundError:
        LOG.warning(f"配置文件未找到: {path}，将使用默认值。")
        return default_value
    except Exception as e:
        LOG.error(f"解析YAML文件失败: {path}，错误: {e}")
        return None

def load_all_configs():
    LOG.info("开始加载所有配置文件...")

    app_config = _load_yaml_file(APP_CONFIG_PATH)
    if app_config is None: 
        LOG.critical(f"主配置文件 {APP_CONFIG_PATH} 加载失败，无法继续。")
        return None

    nodes_config = _load_yaml_file(NODES_CONFIG_PATH, default_value={'nodes': []})
    profiles_config = _load_yaml_file(PROFILES_CONFIG_PATH, default_value={'profiles': {}})
    thresholds_config = _load_yaml_file(THRESHOLDS_CONFIG_PATH, default_value={'thresholds': {}})

    all_configs = {**app_config}
    all_configs['nodes'] = nodes_config.get('nodes', [])
    all_configs['profiles'] = profiles_config.get('profiles', {})
    all_configs['thresholds'] = thresholds_config.get('thresholds', {})

    LOG.info(f"所有配置加载完成。应用配置键: {list(all_configs.keys())}")
    LOG.info(f"加载了 {len(all_configs['nodes'])} 个节点, {len(all_configs['profiles'])} 个profile。")
             
    return all_configs