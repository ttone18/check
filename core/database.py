import sqlite3
import time
from datetime import datetime, timezone, timedelta
import pymysql
from pymysql import connect
from pymysql.err import Error as mysql_error
import logbook

from .model import (
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
            status TEXT, create_at TEXT, update_at TEXT,
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
        return record
    except sqlite3.Error as e:
        LOG.error(f"查询 SQLite 记录失败 (host={host}, type={issue_type}): {e}")
        return None

def upsert_sqlite_record(conn, record_data):
    if not conn:
        LOG.warning("SQLite连接无效，无法更新/插入记录。")
        return
        
    bj_time = datetime.now(timezone(timedelta(hours=8))).isoformat()
    sql = f'''
        INSERT INTO {TABLE_NAME} (host, hostname, type, extra, status, create_at, update_at)
        VALUES (:host, :hostname, :type, :extra, :status, :create_at, :update_at)
        ON CONFLICT(host, type) DO UPDATE SET
            hostname=excluded.hostname,
            extra=excluded.extra,
            status=excluded.status,
            update_at=excluded.update_at
    '''
    try:
        record_data.setdefault('create_at', bj_time)
        record_data['update_at'] = bj_time
        
        cursor = conn.cursor()
        cursor.execute(sql, record_data)
        conn.commit()
        LOG.debug(f"数据库 upsert 成功: {record_data.get('host')} {record_data.get('type')}")
    except sqlite3.Error as e:
        LOG.error(f'数据库 upsert 失败: {e}')
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
        return cursor.execute(sql, tuple(issue_types)).fetchall()
    except sqlite3.Error as e:
        LOG.error(f"按类型查询活动故障失败: {e}")
        return []

_mysql_conn = None

def init_mysql(db_config):
    global _mysql_conn
    if not db_config or not all([db_config.get(k) for k in ['host', 'port', 'user', 'password', 'db_name']]):
        LOG.warning("MySQL 配置不完整，将跳过 MySQL 功能。")
        return None

    retries = MAX_RETRIES
    while retries > 0:
        try:
            conn = connect(
                host=db_config['host'], port=db_config['port'], user=db_config['user'],
                password=db_config['password'], database=None, connection_timeout=10,
                charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor
            )
            LOG.info("成功连接到 MySQL 服务器。")

            with conn.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_config['db_name']}`")
                conn.select_db(db_config['db_name'])
                if EVENTS_ALARMS in TABLE_CREATE_SQL:
                    cursor.execute(TABLE_CREATE_SQL[EVENTS_ALARMS])
            conn.commit()

            _mysql_conn = conn
            LOG.info(f"成功初始化并连接到 MySQL 数据库: {db_config['db_name']}")
            return _mysql_conn
        
        except mysql_error as e:
            LOG.error(f"连接或初始化 MySQL 失败: {e}")
            retries -= 1
            if retries > 0:
                LOG.info(f"将在 {RETRY_INTERVAL} 秒后重试... ({retries}次剩余)")
                time.sleep(RETRY_INTERVAL)
            else:
                LOG.critical("达到最大重试次数，MySQL 功能被禁用。")
                return None

def write_to_mysql(result):
    global _mysql_conn
    if not _mysql_conn:
        LOG.debug("MySQL 连接不可用，跳过写入。")
        return

    try:
        _mysql_conn.ping(reconnect=True)
        
        with _mysql_conn.cursor() as cursor:
            current_time = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            sql = f'''
                INSERT INTO {EVENTS_ALARMS} (host_ip, host_name, type, detail, timestamp) 
                VALUES (%s, %s, %s, %s, %s)
            '''
            cursor.execute(sql, (
                result.get(KEY_HOST, 'N/A'),
                result.get(KEY_HOSTNAME, 'N/A'),
                result.get(KEY_TYPE, 'N/A'),
                str(result.get(KEY_EXTRA, 'N/A')),
                current_time
            ))
        _mysql_conn.commit()
        LOG.debug(f"成功写入一条事件到 MySQL: {result.get(KEY_HOST)} - {result.get(KEY_TYPE)}")
    except mysql_error as e:
        LOG.error(f"MySQL 数据库操作失败: {e}")
        if _mysql_conn:
            _mysql_conn.close()
            _mysql_conn = None
    except Exception as e:
        LOG.error(f"写入 MySQL 时发生未处理的异常: {e}")
