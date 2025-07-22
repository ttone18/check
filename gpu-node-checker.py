import sys
import time
import schedule
import logbook
from logbook.handlers import StreamHandler
from functools import partial
from multiprocessing import Pool, Manager

from core import config 
from core import database, reporter, runners, discover
from core.ssh_client import create_ssh_client
from core.models import *

LOG = logbook.Logger(__name__)

def setup_logging():
    log_format = ('[{record.time:%Y-%m-%d %H:%M:%S.%f%z}] {record.level_name}: {record.channel}: '
                  '[{record.process_name}] {record.message}')
    StreamHandler(sys.stdout, format_string=log_format).push_application()
    return logbook.Logger("GPU-INSPECTOR")

def process_one_node(node_spec, runner_type, all_profiles, app_config, db_connections, lock):
    host = node_spec['host']
    hostname = node_spec.get('hostname', host)
    LOG.info(f"[{hostname}] 开始处理节点，任务类型: '{runner_type}'")

    # 1. 建立SSH连接
    client, ssh_error = create_ssh_client(
        host=host,
        port=node_spec.get('port', 22),
        username=node_spec.get('username'),
        password=node_spec.get('password')
    )

    if not client:
        LOG.error(f"[{hostname}] SSH 连接失败: {ssh_error}")
        result = {KEY_HOST: host, KEY_HOSTNAME: hostname, KEY_TYPE: TYPE_SSH, KEY_EXTRA: ssh_error}
        with lock:
            reporter.process_connection_failure(node_spec, result)
        return

    try:
        # 2. 动态发现GPU厂商
        detected_vendor = discover.detect_gpu_vendor_on_remote(client)
        LOG.info(f"[{hostname}] 自动发现GPU厂商为: '{detected_vendor}'")

        # 3. 根据厂商和任务类型选择正确的检查项
        selected_profile = all_profiles.get(detected_vendor, all_profiles.get('unknown', {}))
        checks_to_run = selected_profile.get('checks', {}).get(runner_type, [])

        if not checks_to_run:
            LOG.warning(f"[{hostname}] 对于厂商 '{detected_vendor}' 和任务类型 '{runner_type}'，没有配置任何检查项，跳过。")
            return

        # 4. 执行检查 (使用通用的runner)
        check_results = runners.run_specific_checks(client, node_spec, checks_to_run)
        
        # 5. 处理和上报结果
        for check_name, result in check_results.items():
            is_success = result.get(KEY_SUCCESS, False)
            issue_types = result.get(KEY_TYPES, [])
            
            with lock:
                if is_success:
                    reporter.process_results(node_specs, check_results, db_connections) 
            
    except Exception as e:
        LOG.error(f"[{hostname}] 在执行巡检时发生未知异常: {e}", exc_info=True)
    finally:
        if client: client.close()
        LOG.info(f"[{hostname}] 节点处理完毕。")


def run_inspection_cycle(runner_type, node_specs, all_profiles, app_config, db_connections, lock):
    if not node_specs:
        LOG.warning("节点列表为空，跳过本轮巡检。")
        return

    LOG.info(f"====== 开始新一轮巡检 (任务类型: '{runner_type}'), 目标节点数: {len(node_specs)} ======")
    
    task_func = partial(process_one_node, 
                        runner_type=runner_type,
                        all_profiles=all_profiles,
                        app_config=app_config,
                        db_connections=db_connections,
                        lock=lock)
    
    with Pool(processes=app_config.get('MAX_WORKERS', 5)) as pool:
        pool.map(task_func, node_specs)
    
    LOG.info(f"====== 本轮巡检 (任务类型: '{runner_type}') 完成 ======")


def main():
    LOG = setup_logging()
    LOG.info("========= GPU 节点巡检程序启动 =========")
    
    # 1. 加载所有配置
    app_config = config.load_config()
    all_profiles = config.load_profiles()
    node_specs = app_config.get('node', [])

    if not node_specs:
        LOG.critical("在 config.yaml 中未找到任何节点配置，程序退出。"); sys.exit(1)
    if not all_profiles:
        LOG.critical("在 profiles.yaml 中未找到任何策略配置，程序退出。"); sys.exit(1)

    if not app_config:
        LOG.critical("主配置文件加载失败，程序退出。"); sys.exit(1)
        
    all_configs = config.load_all_configs()
    if not all_configs:
        LOG.critical("YAML配置文件加载失败，程序退出。"); sys.exit(1)
    
    node_specs = all_configs.get('nodes', [])
    all_profiles = all_configs.get('profiles', {})

    # 2. 初始化数据库连接
    sqlite_conn = database.init_sqlite(app_config.get('SQLITE_DB_PATH'))
    if not sqlite_conn:
        LOG.critical("SQLite 数据库初始化失败，程序退出。"); sys.exit(1)

    mysql_conn = database.init_mysql(app_config.get('MYSQL'))

    # 3. 创建多进程安全锁和共享数据库连接字典
    manager = Manager()
    process_lock = manager.Lock()
    db_connections = manager.dict({
        'sqlite': sqlite_conn,
        'mysql': mysql_conn
    })

    # 4. 准备调度任务的通用参数
    task_args = {
        'node_specs': node_specs,
        'all_profiles': all_profiles,
        'app_config': app_config,
        'db_connections': db_connections,
        'lock': process_lock
    }

    # 5. 安排定时任务
    gpu_interval = app_config.get('GPU_CHECK_INTERVAL_SECONDS', 30)
    schedule.every(gpu_interval).seconds.do(run_inspection_cycle, runner_type='gpu', **task_args)
    LOG.info(f"已安排高频 GPU 检查，每 {gpu_interval} 秒执行一次。")

    sys_interval = app_config.get('SYSTEM_CHECK_INTERVAL_MINUTES', 10)
    schedule.every(sys_interval).minutes.do(run_inspection_cycle, runner_type='system', **task_args)
    LOG.info(f"已安排低频系统检查，每 {sys_interval} 分钟执行一次。")

    net_interval = app_config.get('NETWORK_CHECK_INTERVAL_MINUTES', 5)
    schedule.every(net_interval).minutes.do(run_inspection_cycle, runner_type='network', **task_args)
    LOG.info(f"-> 已安排 'network' 检查，每 {net_interval} 分钟执行一次。")

    storage_interval = app_config.get('STORAGE_CHECK_INTERVAL_MINUTES', 10)
    schedule.every(storage_interval).minutes.do(run_inspection_cycle, runner_type='storage', **task_args)
    LOG.info(f"-> 已安排 'storage' 检查，每 {storage_interval} 分钟执行一次。")

    # 安排每日 P3 汇总报告任务
    schedule.every().day.at("09:00").do(
        reporter.send_daily_p3_summary,
        db_conn=sqlite_conn,
        app_config=app_config
    )
    LOG.info("已安排每日P3汇总报告任务，将于每天09:00执行。")
    
    LOG.info("程序启动，立即执行一次全量检查...")
    run_inspection_cycle(runner_type='gpu', **task_args)
    run_inspection_cycle(runner_type='system', **task_args)
    run_inspection_cycle(runner_type='network', **task_args)
    run_inspection_cycle(runner_type='storage', **task_args)

    LOG.info("所有任务已调度，进入主循环... (按 Ctrl+C 退出)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        LOG.info("收到退出信号 (Ctrl+C)...")
    finally:
        LOG.info("正在关闭数据库连接...")
        if sqlite_conn: sqlite_conn.close()
        if mysql_conn and mysql_conn.is_connected(): mysql_conn.close()
        LOG.info("程序已退出。")


if __name__ == '__main__':
    main()