import sqlite3
import time
from datetime import datetime, timezone, timedelta
import pymysql
from pymysql import connect
from pymysql.err import Error as mysql_error
import logbook

from .models import (
    TABLE_NAME, MAX_RETRIES, RETRY_INTERVAL, KEY_HOST, KEY_HOSTNAME, 
    KEY_TYPE, KEY_EXTRA, EVENTS_ALARMS, TABLE_CREATE_SQL
)

LOG = logbook.Logger(__name__)

def init_sqlite(db_path="venus_checker.db"):
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row  
        _ensure_sqlite_table(conn)
        LOG.info(f"成功初始化并连接到 SQLite 数据库: {db_path}")
        return conn
    except sqlite3.Error as e:
        LOG.critical(f'SQLite 初始化失败，程序可能无法正常记录状态: {e}')
        return None

def _ensure_sqlite_table(conn):
    create_table_sql = f'''
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            host TEXT, hostname TEXT, type TEXT, extra TEXT,
            status TEXT, priority TEXT, create_at TEXT, update_at TEXT,
            PRIMARY KEY (host, type)
        )
    '''
    try:
        cursor = conn.cursor()
        cursor.execute(create_table_sql)
        conn.commit()
    except sqlite3.Error as e:
        LOG.error(f"创建 SQLite 表 '{TABLE_NAME}' 失败: {e}")
        raise

def query_sqlite_record(conn, host, issue_type):
    if not conn:
        LOG.warning("SQLite连接无效，无法查询记录。")
        return None
    try:
        sql = f'SELECT * FROM {TABLE_NAME} WHERE host = ? AND type = ?'
        cursor = conn.cursor()
        record = cursor.execute(sql, (host, issue_type)).fetchone()

        if record:
            return dict(record)
        return None

    except sqlite3.Error as e:
        LOG.error(f"查询 SQLite 记录失败 (host={host}, type={issue_type}): {e}")
        return None

def upsert_sqlite_record(conn, record_data):
    if not conn:
        LOG.warning("SQLite连接无效，无法更新/插入记录。")
        return

    LOG.debug(f"upsert_sqlite_record接收到的原始数据: {record_data}")

    if not record_data.get('host') or not record_data.get('type'):
        LOG.error(f"数据库Upsert中止：传入的数据缺少host或type字段。数据: {record_data}")
        return

    bj_time = datetime.now(timezone(timedelta(hours=8))).isoformat()

    data_for_sql = {
        'host': record_data.get('host'),
        'hostname': record_data.get('hostname'),
        'type': record_data.get('type'),
        'extra': record_data.get('extra'),
        'status': record_data.get('status'),
        'priority': record_data.get('priority', 'N/A'),
        'create_at': record_data.get('create_at', bj_time),
        'update_at': bj_time
    }

    sql = f'''
        INSERT INTO {TABLE_NAME} (host, hostname, type, extra, status, priority, create_at, update_at)
        VALUES (:host, :hostname, :type, :extra, :status, :priority, :create_at, :update_at)
        ON CONFLICT(host, type) DO UPDATE SET
            hostname=excluded.hostname,
            extra=excluded.extra,
            status=excluded.status,
            priority=excluded.priority,
            update_at=excluded.update_at
    '''
    try:
        cursor = conn.cursor()
        cursor.execute(sql, data_for_sql)
        conn.commit()
        
        LOG.debug(f"数据库upsert成功。写入的数据: {data_for_sql}")

    except sqlite3.Error as e:
        LOG.error(f'数据库 upsert 失败: {e}. 尝试写入的数据: {data_for_sql}')
        if conn: conn.rollback()


def update_issue_status(conn, host, issue_type, status):
    if not conn:
        LOG.warning("SQLite连接无效，无法更新状态。")
        return

    bj_time = datetime.now(timezone(timedelta(hours=8))).isoformat()
    sql = f'''
        UPDATE {TABLE_NAME} 
        SET status = ?, update_at = ?
        WHERE host = ? AND type = ? AND status != ?
    '''
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (status, bj_time, host, issue_type, status))
        if cursor.rowcount > 0: 
             LOG.info(f"数据库状态更新成功: {host} {issue_type} -> {status}")
        conn.commit()
    except sqlite3.Error as e:
        LOG.warning(f'更新状态失败 (host={host}, type={issue_type}): {e}')
        if conn: conn.rollback()

def query_active_issues_by_types(conn, issue_types):
    if not conn or not issue_types:
        return []
    try:
        placeholders = ', '.join('?' for _ in issue_types)
        sql = f"SELECT * FROM {TABLE_NAME} WHERE status != 'resolved' AND type IN ({placeholders})"
        cursor = conn.cursor()
        rows = cursor.execute(sql, tuple(issue_types)).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        LOG.error(f"按类型查询活动故障失败: {e}")
        return []

def init_mysql(db_config):
    if not db_config or not all([db_config.get(k) for k in ['host', 'port', 'user', 'password', 'db_name']]):
        LOG.warning("MySQL 配置不完整，将跳过 MySQL 功能。")
        return False

    retries = MAX_RETRIES
    while retries > 0:
        try:
            conn = connect(
                host=db_config['host'], port=db_config['port'], user=db_config['user'],
                password=db_config['password'], database=None, connection_timeout=10,
                charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
            )
            
            with conn.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_config['db_name']}`")
                conn.select_db(db_config['db_name'])
                if EVENTS_ALARMS in TABLE_CREATE_SQL:
                    cursor.execute(TABLE_CREATE_SQL[EVENTS_ALARMS])
            conn.commit()
            conn.close()
            LOG.info(f"成功初始化 MySQL 数据库和表: {db_config['db_name']}")
            return True
        
        except mysql_error as e:
            LOG.error(f"连接或初始化 MySQL 失败: {e}")
            retries -= 1
            if retries > 0:
                LOG.info(f"将在 {RETRY_INTERVAL} 秒后重试... ({retries}次剩余)")
                time.sleep(RETRY_INTERVAL)
            else:
                LOG.critical("达到最大重试次数，MySQL 功能被禁用。")
                return False

def get_mysql_connection(db_config):
    if not db_config:
        return None
    try:
        conn = connect(
            host=db_config['host'], port=db_config['port'], user=db_config['user'],
            password=db_config['password'], database=db_config['db_name'],
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except mysql_error as e:
        LOG.error(f"获取新的 MySQL 连接失败: {e}")
        return None

def write_to_mysql(conn, event_data):
    if not conn:
        LOG.debug("MySQL connection is not available, skipping write.")
        return

    cursor = None
    try:
        cursor = conn.cursor()
        sql = """
        INSERT INTO your_alert_table (
            hostname, check_name, status, value, message, 
            check_time, profile
        ) VALUES (
            %(host)s, %(check_name)s, %(status)s, %(value)s, %(message)s, 
            %(check_time)s, %(profile)s
        )
        """
        data_to_insert = {
            'host': event_data.get('host'),
            'check_name': event_data.get('check_name'),
            'status': event_data.get('status'),
            'value': str(event_data.get('value', '')),
            'message': event_data.get('message'),
            'check_time': event_data.get('check_time'),
            'profile': event_data.get('profile')
        }
        
        cursor.execute(sql, data_to_insert)
        conn.commit()
        LOG.info(f"Successfully wrote alert for {event_data.get('host')} to MySQL.")
        
    except Exception as e:
        LOG.error(f"Failed to write to MySQL: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
