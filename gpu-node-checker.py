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

_process_global_config = {}

def init_worker(config_payload):
    global _process_global_config
    _process_global_config.update(config_payload)
    setup_logging() 

def setup_logging():
    log_format = ('[{record.time:%Y-%m-%d %H:%M:%S.%f%z}] {record.level_name}: {record.channel}: '
                  '[{record.process_name}] {record.message}')
    StreamHandler(sys.stdout, format_string=log_format).push_application()
    return logbook.Logger("GPU-INSPECTOR")

def process_one_node(node_spec):
    runner_type = _process_global_config['runner_type']
    app_config = _process_global_config['app_config']
    all_profiles = _process_global_config['all_profiles']
    thresholds = _process_global_config['thresholds']
    
    host = node_spec['host']
    hostname = node_spec.get('hostname', node_spec['host'])
    LOG.info(f"[{hostname}] 开始处理节点，任务类型: '{runner_type}'")

    sqlite_conn = database.init_sqlite(app_config.get('SQLITE_DB_PATH'))
    mysql_conn = database.get_mysql_connection(app_config.get('MYSQL'))
    db_connections = {'sqlite': sqlite_conn, 'mysql': mysql_conn}

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
        reporter.handle_failed_issue(sqlite_conn, mysql_conn, app_config, result)
        if sqlite_conn: sqlite_conn.close()
        if mysql_conn: mysql_conn.close()
        return

    try:
        # 2. 动态发现GPU厂商
        profile_name = discover.discover_node_profile(client, hostname)
        LOG.info(f"[{hostname}] 自动发现节点 Profile 为: '{profile_name}'")

        # 3. 根据厂商和任务类型选择正确的检查项
        selected_profile_checks = all_profiles.get(profile_name, {})
        checks_to_run = selected_profile_checks.get(runner_type, [])

        if not checks_to_run:
            LOG.warning(f"[{hostname}] 对于 Profile '{profile_name}' 和任务类型 '{runner_type}'，没有配置任何检查项，跳过。")
            if client: client.close()
            if sqlite_conn: sqlite_conn.close()
            if mysql_conn: mysql_conn.close()
            return

        # 4. 执行检查 (使用通用的runner)
        check_results = runners.run_specific_checks(client, node_spec, thresholds, checks_to_run)
        
        # 5. 处理和上报结果
        if check_results:
            reporter.process_results(node_spec, check_results, db_connections, app_config)
            
    except Exception as e:
        LOG.error(f"[{hostname}] 在执行巡检时发生未知异常: {e}", exc_info=True)
    finally:
        if client: client.close()
        if sqlite_conn: sqlite_conn.close()
        if mysql_conn: mysql_conn.close()
        LOG.info(f"[{hostname}] 节点处理完毕。")


def run_inspection_cycle(runner_type, node_specs, all_profiles, app_config):
    if not node_specs:
        LOG.warning("节点列表为空，跳过本轮巡检。")
        return

    LOG.info(f"====== 开始新一轮巡检 (任务类型: '{runner_type}') ... ======")
    
    config_payload = {
        'runner_type': runner_type,
        'all_profiles': all_profiles,
        'app_config': app_config,
        'thresholds': thresholds
    }
    
    with Pool(processes=app_config.get('MAX_WORKERS', 5),
              initializer=init_worker, 
              initargs=(config_payload,)) as pool:
        pool.map(process_one_node, node_specs)
    
    LOG.info(f"====== 本轮巡检 (任务类型: '{runner_type}') 完成 ======")

def run_p3_summary_job(app_config):
    LOG.info("开始执行每日P3汇总任务...")
    db_conn = database.init_sqlite(app_config.get('SQLITE_DB_PATH'))
    if not db_conn:
        LOG.error("无法为P3汇总任务创建数据库连接，任务跳过。")
        return
        
    try:
        reporter.send_daily_p3_summary(db_conn, app_config)
    except Exception as e:
        LOG.error(f"执行P3汇总任务时出错: {e}", exc_info=True)
    finally:
        if db_conn:
            db_conn.close()
            LOG.info("P3汇总任务完成，数据库连接已关闭。")

def main():
    LOG = setup_logging()
    LOG.info("========= GPU 节点巡检程序启动 =========")
    
    # 1. 加载所有配置
    all_configs = config.load_all_configs()
    if not all_configs:
        LOG.critical("配置文件加载失败，程序退出。")
        sys.exit(1)
    
    node_specs = all_configs.get('nodes', [])
    all_profiles = all_configs.get('profiles', {})
    thresholds = all_configs.get('thresholds', {}) 
    app_config = all_configs

    if not node_specs:
        LOG.critical("在 nodes.yaml 中未找到任何节点配置 (nodes)，程序退出。")
        sys.exit(1)
    if not all_profiles:
        LOG.critical("在 profiles.yaml 中未找到任何策略配置 (profiles)，程序退出。")
        sys.exit(1)

    # 2. 初始化数据库连接
    database.init_sqlite(all_configs.get('SQLITE_DB_PATH'))
    database.init_mysql(all_configs.get('MYSQL'))

    # 3. 准备调度任务的通用参数
    task_args = {
        'node_specs': node_specs,
        'all_profiles': all_profiles,
        'app_config': app_config,
        'thresholds': thresholds
    }

    # 4. 安排定时任务
    gpu_interval = app_config.get('GPU_CHECK_INTERVAL_SECONDS', 30)
    schedule.every(gpu_interval).seconds.do(run_inspection_cycle, runner_type='gpu', **task_args)
    LOG.info(f"已安排高频 GPU 检查，每 {gpu_interval} 秒执行一次。")

    sys_interval = app_config.get('SYSTEM_CHECK_INTERVAL_MINUTES', 10)
    schedule.every(sys_interval).minutes.do(run_inspection_cycle, runner_type='system', **task_args)
    LOG.info(f"已安排低频系统检查，每 {sys_interval} 分钟执行一次。")

    # 安排每日 P3 汇总报告任务
    schedule.every().day.at("09:00").do(run_p3_summary_job, app_config=app_config)
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
        LOG.info("程序已退出。")


if __name__ == '__main__':
    main()