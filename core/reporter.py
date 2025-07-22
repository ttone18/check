import json
import requests
import logbook
from datetime import datetime, timezone, timedelta
from utils.log import LOG

from . import database 
from .models import *

LOG = logbook.Logger(__name__)
HIGH_FREQ_DEBOUNCE_CACHE = {} 
DEBOUNCE_WINDOW_SECONDS = 60 


def _send_feishu_alert(app_config, result, is_recovery=False, is_duplicate=False):
    issue_type = result.get(KEY_TYPE)
    metadata = ALERT_METADATA.get(issue_type)
    if not metadata:
        LOG.warning(f"未找到告警类型 '{issue_type}' 的元数据，跳过发送。")
        return
    
    if not is_recovery and metadata['priority'] == P3:
        LOG.info(f"检测到P3级别事件: [{issue_type}] on [{result.get(KEY_HOSTNAME)}]。仅记录，等待每日汇总。")
        return
    
    webhook_urls = app_config.get('FEISHU_WEBHOOKS', {})
    target_group = metadata.get('group')
    target_url = webhook_urls.get(target_group)
    if not target_url:
        LOG.error(f"未在配置中找到告警群组 '{target_group}' 的Webhook URL。")
        return
    
    priority = metadata['priority']
    node = result.get(KEY_HOSTNAME, "N/A")
    ip = result.get(KEY_HOST, "N/A")
    
    if is_recovery:
        title = f"【故障恢复】{metadata['title']} - {node}"
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"已恢复故障类型: {issue_type}"}],
            [{"tag": "text", "text": f"恢复时间: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}"}]
        ]
    elif is_duplicate:
        title = f"【重复告警】{metadata['title']} - {node}"
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"类型: {issue_type} (重复告警)"}],
            [{"tag": "text", "text": f"描述: {str(result.get(KEY_EXTRA, 'N/A'))}"}],
        ]
    else:
        title = f"【{priority}】{metadata['title']} - {node}"
        at_all_tag = ""
        if priority in [P0, P1]:
            at_all_tag = ' <at user_id="all">所有人</at>'
        
        content = [
            [{"tag": "text", "text": f"节点: {node}"}],
            [{"tag": "text", "text": f"IP: {ip}"}],
            [{"tag": "text", "text": f"类型: {issue_type}"}],
            [{"tag": "text", "text": f"描述: {str(result.get(KEY_EXTRA, 'N/A'))}{at_all_tag}"}],
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
    """将告警数据通过Webhook同步到飞书表格。"""
    webhook_urls = app_config.get('FEISHU_WEBHOOKS', {})
    table_webhook_url = webhook_urls.get('table_sync_webhook')

    if not table_webhook_url:
        LOG.debug("飞书表格同步Webhook (table_sync_webhook) 未配置，跳过写入。")
        return

    payload = {
        'host': alarm_data.get(KEY_HOST),
        'hostname': alarm_data.get(KEY_HOSTNAME),
        'type': alarm_data.get(KEY_TYPE),
        'extra': str(alarm_data.get(KEY_EXTRA)),
        'time': datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    }
    
    try:
        resp = requests.post(table_webhook_url, json=payload, timeout=15)
        if resp.status_code == 200:
            LOG.info(f"告警已同步到飞书表格: {payload['hostname']} - {payload['type']}")
        else:
            LOG.warning(f"同步飞书表格响应: {resp.status_code} {resp.text}")
    except Exception as e:
        LOG.error(f"同步飞书表格到 {table_webhook_url} 异常: {e}")

def handle_failed_issue(db_conn, app_config, result):
    host = result.get(KEY_HOST)
    issue_type = result.get(KEY_TYPE)
    current_extra = str(result.get(KEY_EXTRA))
    
    alarm_key = f"{host}:{issue_type}"
    current_time = time.time()

    expired_keys = [k for k, ts in HIGH_FREQ_DEBOUNCE_CACHE.items() if current_time - ts > DEBOUNCE_WINDOW_SECONDS]
    for k in expired_keys:
        del HIGH_FREQ_DEBOUNCE_CACHE[k]

    if alarm_key in HIGH_FREQ_DEBOUNCE_CACHE:
        LOG.info(f"检测到高频重复告警: {alarm_key}。仅发送标记通知，不写入数据。")
        _send_feishu_alert(app_config, result, is_recovery=False, is_duplicate=True)
        return

    old_record = database.query_sqlite_record(db_conn, host, issue_type)
    should_report = False
    if old_record is None:
        should_report = True
        LOG.info(f"检测到新发故障: {host} - {issue_type} - {current_extra}")
    elif old_record['status'] != 'reported':
        should_report = True
        LOG.info(f"检测到故障复发: {host} - {issue_type}")
    elif old_record['extra'] != current_extra:
        should_report = True
        LOG.info(f"检测到故障详情变化: {host} - {issue_type}. 旧: {old_record['extra']}, 新: {current_extra}")
    else:
        LOG.debug(f"故障持续存在，无需重复告警: {host} - {issue_type}")

    if should_report:
        LOG.info(f"执行首次告警完整流程: {alarm_key}")
        _send_to_feishu_table(app_config, result)
        database.write_to_mysql(result)
        _send_feishu_alert(app_config, result, is_recovery=False)
        HIGH_FREQ_DEBOUNCE_CACHE[alarm_key] = current_time
    else:
        LOG.debug(f"故障持续存在 (已在DB中)，无需重复告警: {alarm_key}")
    
    record_to_save = {
        'host': host,
        'hostname': result.get(KEY_HOSTNAME),
        'type': issue_type,
        'extra': current_extra,
        'status': 'reported'
    }
    database.upsert_sqlite_record(db_conn, record_to_save)

def handle_resolved_issue(db_conn, app_config, host, issue_type):
    old_record = database.query_sqlite_record(db_conn, host, issue_type)
    if old_record and old_record['status'] == 'reported':
        LOG.info(f"检测到故障已恢复: {host} - {issue_type}. 将更新数据库状态并发送恢复通知。")
        database.update_issue_status(db_conn, host, issue_type, "resolved")
        recovery_event = dict(old_record)
        recovery_event[KEY_EXTRA] = "ISSUE RESOLVED"
        database.write_to_mysql(recovery_event)
        _send_feishu_alert(app_config, dict(old_record), is_recovery=True)

#P3 汇总功能
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
            hostname = event['hostname']
            if hostname not in events_by_host: events_by_host[hostname] = []
            events_by_host[hostname].append(f"{event['type']}: {event['extra']}")

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
