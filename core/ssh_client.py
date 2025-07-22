import time
import paramiko
import logbook

LOG = logbook.Logger(__name__)

def create_ssh_client(host, port, username, password, retries=3, delay=5):
    client = None
    error = ""
    for attempt in range(retries):
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=host, port=port, username=username, password=password, timeout=10)
            LOG.debug(f"成功连接到 {username}@{host}:{port}")
            return client, error  # 成功连接，返回
        except paramiko.ssh_exception.NoValidConnectionsError as e:
            LOG.error(f"无法建立有效的连接 (尝试 {attempt+1}/{retries}): {e}")
            client, error = None, str(e)
        except paramiko.ssh_exception.AuthenticationException as e:
            LOG.error(f"认证失败 (尝试 {attempt+1}/{retries}): {e}")
            client, error = None, str(e)
            break  # 认证失败时不再重试
        except paramiko.ssh_exception.SSHException as e:
            LOG.error(f"SSH异常 (尝试 {attempt+1}/{retries}): {e}")
            client, error = None, "SSH_EXCEPTION_INTERNAL"
        except TimeoutError as e:
            LOG.error(f"连接超时 (尝试 {attempt+1}/{retries}): {e}")
            client, error = None, str(e)
        except Exception as e:
            LOG.error(f"SSH未知异常 (尝试 {attempt+1}/{retries}): {e}")
            client, error = None, f"ssh unknown exception {e}"

        if attempt < retries - 1:
            LOG.info(f"等待 {delay} 秒后重试...")
            time.sleep(delay)

    return client, error