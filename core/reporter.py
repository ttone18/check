import json
import time
import requests
import logbook
from datetime import datetime, timezone, timedelta
from . import database 
from .models import *

LOG = logbook.Logger(__name__)
HIGH_FREQ_DEBOUNCE_CACHE = {} 
DEBOUNCE_WINDOW_SECONDS = 60 

def _send_feishu_alert(app_config, result, is_recovery=False, is_duplicate=False):
    issue_type = result.get(KEY_TYPE)
    metadata = ALERT_METADATA.get(issue_type, {})

    priority = result.get('priority', metadata.get('priority', 'N/A'))

    if not metadata:
        LOG.warning(f"未找到告警类型 '{issue_type}' 的元数据，跳过发送。")
        return

    if not is_recovery and priority == P3:
        LOG.info(f"检测到P3级别事件: [{issue_type}] on [{result.get(KEY_HOSTNAME)}]。仅记录，等待每日汇总。")
        return
    
    webhook_urls = app_config.get('FEISHU_WEBHOOKS', {})
    target_group = metadata.get('group')
    target_url = webhook_urls.get(target_group)
    if not target_url:
        LOG.error(f"未在配置中找到告警群组 '{target_group}' 的Webhook URL。")
        return
    
    node = result.get(KEY_HOSTNAME, "N/A")
    ip = result.get(KEY_HOST, "N/A")

    if is_recovery:
        title = f"【故障恢复】{metadata.get('title', issue_type)} - {node}"
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"优先级: {priority}"}],
            [{"tag": "text", "text": f"已恢复故障类型: {issue_type}"}],
            [{"tag": "text", "text": f"恢复时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}"}]
        ]
    elif is_duplicate:
        title = f"【重复告警】{metadata.get('title', issue_type)} - {node}"
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"优先级: {priority}"}],
            [{"tag": "text", "text": f"类型: {issue_type} (重复告警)"}],
            [{"tag": "text", "text": f"描述: {str(result.get(KEY_EXTRA, 'N/A'))}"}],
        ]
    else:
        title = f"【{priority}】{metadata.get('title', issue_type)} - {node}"
        description = str(result.get(KEY_EXTRA, 'N/A'))
        description_line = [{"tag": "text", "text": f"描述: {description} "}]
        if priority in [P0, P1]:
            description_line.append({"tag": "at", "user_id": "all"})
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"优先级: {priority}"}],
            [{"tag": "text", "text": f"类型: {issue_type}"}],
            description_line,
            [{"tag": "text", "text": f"时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}"}]
        ]
    
    data = {"msg_type": "post", "content": {"post": {"zh_cn": {"title": title, "content": content}}}}

    try:
        response = requests.post(target_url, json=data, timeout=10)
        response.raise_for_status()
        LOG.info(f"成功发送通知到群组 '{target_group}': {title}")
    except requests.RequestException as e:
        LOG.error(f"发送飞书通知失败: {e}")

def _send_to_feishu_table(app_config, alarm_data):
    webhook_urls = app_config.get('FEISHU_WEBHOOKS', {})
    table_webhook_url = webhook_urls.get('table_sync_webhook')
    if not table_webhook_url:
        LOG.debug("飞书表格同步Webhook (table_sync_webhook) 未配置，跳过写入。")
        return

    payload = {
        'host': alarm_data.get(KEY_HOST),
        'hostname': alarm_data.get(KEY_HOSTNAME),
        'priority': alarm_data.get('priority', 'N/A'),
        'type': alarm_data.get(KEY_TYPE),
        'extra': str(alarm_data.get(KEY_EXTRA)),
        'success': "False",
        'time': datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    }
    
    try:
        resp = requests.post(table_webhook_url, json=payload, timeout=15)
        if resp.status_code == 200:
            resp_json = resp.json()
            if resp_json.get("code") == 0:
                LOG.info(f"告警已同步到飞书表格: {payload['hostname']} - {payload['type']}")
            else:
                LOG.warning(f"同步飞书表格失败，飞书返回错误: {resp.text}")
        else:
            LOG.warning(f"同步飞书表格HTTP响应异常: {resp.status_code} {resp.text}")
    except Exception as e:
        LOG.error(f"同步飞书表格到 {table_webhook_url} 异常: {e}")

def handle_failed_issue(sqlite_conn, mysql_conn, app_config, result):
    host = result.get(KEY_HOST)
    issue_type = result.get(KEY_TYPE)
    current_extra = str(result.get(KEY_EXTRA))

    metadata = ALERT_METADATA.get(issue_type, {})
    priority_code = metadata.get('priority', 'P3')
    priority_display = metadata.get('display', priority_code)
    result['priority'] = priority_display

    old_record = database.query_sqlite_record(sqlite_conn, host, issue_type)

    if old_record and old_record.get('status') == 'reported' and old_record.get('extra') == current_extra:
        LOG.info(f"检测到持续存在的相同故障: {host} - {issue_type}。将发送标记通知，不写入表格。")
        _send_feishu_alert(app_config, result, is_recovery=False, is_duplicate=True)
        return
    
    LOG.info(f"检测到新/复发/变化的故障，执行完整告警流程: {host} - {issue_type}")
    _send_feishu_alert(app_config, result, is_recovery=False)
    _send_to_feishu_table(app_config, result)
    database.write_to_mysql(mysql_conn, result)
    record_to_save = {
        'host': host,
        'hostname': result.get(KEY_HOSTNAME),
        'priority': priority_display,
        'type': issue_type,
        'extra': current_extra,
        'status': 'reported'
    }
    database.upsert_sqlite_record(sqlite_conn, record_to_save)


def handle_resolved_issue(sqlite_conn, mysql_conn, app_config, host, issue_type):
    old_record = database.query_sqlite_record(sqlite_conn, host, issue_type)
    
    if old_record and old_record.get('status') == 'reported':
        LOG.info(f"检测到故障已恢复: {host} - {issue_type}. 将更新数据库状态并发送恢复通知。")
        database.update_issue_status(sqlite_conn, host, issue_type, "resolved")
        recovery_event = dict(old_record)
        recovery_event["extra"] = "ISSUE RESOLVED" 
        database.write_to_mysql(mysql_conn, recovery_event)
        _send_feishu_alert(app_config, dict(old_record), is_recovery=True)

def send_daily_p3_summary(db_conn, app_config):
    LOG.info("开始生成P3级别事件每日汇总报告...")
    
    p3_types = [issue_type for issue_type, meta in ALERT_METADATA.items() if meta['priority'] == P3]
    if not p3_types:
        LOG.info("系统中未定义P3级别告警，跳过汇总。")
        return

    active_p3_events = database.query_active_issues_by_types(db_conn, p3_types)
    
    webhook_urls = app_config.get('FEISHU_WEBHOOKS', {})
    target_group = "analytics_group"
    target_url = webhook_urls.get(target_group)
    if not target_url:
        LOG.error(f"未找到三线分析群 '{target_group}' 的Webhook URL，无法发送汇总报告。")
        return

    title = f"P3级事件每日汇总报告 - {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d')}"
    
    if not active_p3_events:
        content = [[{"tag": "text", "text": "过去24小时无新增或持续的P3级别事件。"}]]
    else:
        content = []
        events_by_host = {}
        for event in active_p3_events:
            hostname = event.get('hostname', 'N/A')
            if hostname not in events_by_host: events_by_host[hostname] = []
            events_by_host[hostname].append(f"{event.get('type', 'N/A')}: {event.get('extra', 'N/A')}")

        for hostname, details in events_by_host.items():
            content.append([{"tag": "text", "text": f"节点: {hostname}"}])
            for detail in details:
                content.append([{"tag": "text", "text": f"  - {detail}"}])

    data = {"msg_type": "post", "content": {"post": {"zh_cn": {"title": title, "content": content}}}}

    try:
        response = requests.post(target_url, json=data, timeout=10)
        response.raise_for_status()
        LOG.info(f"成功发送P3汇总报告到群组 '{target_group}'")
    except requests.RequestException as e:
        LOG.error(f"发送P3汇总报告失败: {e}")


def process_results(node_spec, check_results, db_connections, app_config):
    sqlite_conn = db_connections.get('sqlite')
    mysql_conn = db_connections.get('mysql')
    host = node_spec.get('host')
    hostname = node_spec.get('hostname', host)
    for check_name, result in check_results.items():
        is_success = result.get(KEY_SUCCESS, False)
        issue_types = result.get(KEY_TYPES, [])
        if not issue_types:
            issue_types = [check_name]
        for issue_type in issue_types:
            event_data = {
                KEY_HOST: host,
                KEY_HOSTNAME: hostname,
                KEY_TYPE: issue_type,
                KEY_EXTRA: result.get(KEY_EXTRA, ''),
            }
            if is_success:
                handle_resolved_issue(sqlite_conn, mysql_conn, app_config, host, issue_type)
            else:
                handle_failed_issue(sqlite_conn, mysql_conn, app_config, event_data)

def process_connection_failure(node_spec, result):
    LOG.error(f"上报连接失败: {node_spec.get('hostname')}")
