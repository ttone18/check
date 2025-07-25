# check
autocheck
## 概述 (Overview)

本系统是一个基于 Python 的自动化巡检工具，旨在对大规模高性能计算集群中的每个节点进行全面的健康检查。它通过 SSH 连接到各个节点，执行预定义的检查命令，并将发现的异常情况通过飞书机器人实时告警。

## 核心功能 (Core Features)

*   检查项覆盖 GPU、网络、存储、系统等多个维度，区分 nvidia gpu 和 muxi
*   支持 P0 (紧急) 到 P3 (记录) 四个级别的告警，不同级别告警对应不同功能
*   智能告警
    *   对持续存在的同一故障，仅发送一次“新发告警”并记录到表格，后续只发送“重复告警”通知
    *   当检测到之前报告的故障已恢复时，会自动发送恢复通知。
*   通过 config 管理所有配置，包括节点信息、告警阈值和 Webhook URL
*   告警事件会自动同步到飞书多维表格，便于追踪和复盘。同时支持写入 MySQL 数据库做长期数据分析

## 文件结构 (File Structure)
```
.
├── gpu-node-checker.py     # 项目主入口，启动巡检
|
├── configs/                # YAML 配置文件目录
│   ├── app_config.yaml     # 应用级配置 (Webhook, 数据库)
│   ├── nodes.yaml          # 定义被巡检的节点列表
│   ├── profiles.yaml       # 定义巡检策略 (Profile)，将检查项组合成不同的策略集
│   └── thresholds.yaml     # 定义所有检查项的告警阈值
|
├── checks/                 # 具体的检查项实现
│   ├── gpu_checks.py       # NVIDIA GPU 相关检查
│   ├── muxi_checks.py      # 沐曦 GPU 相关检查
│   ├── network_checks.py   # 网络相关检查
│   ├── storage_checks.py   # 存储 (如 GPFS) 相关检查
│   └── system_checks.py    # 基础系统 (CPU, 内存, 磁盘) 相关检查
|
└── core/                   # 核心逻辑与框架组件
    ├── config.py           # YAML 配置文件加载器
    ├── database.py         # 数据库交互模块 (SQLite, MySQL)
    ├── discover.py         # 检查项发现与注册模块
    ├── executor.py         # 任务执行器，负责命令的实际执行与结果解析
    ├── models.py           # 数据模型定义 (告警类型、优先级、群组)
    ├── reporter.py         # 告警决策与发送模块
    ├── runners.py          # 并发任务调度器
    └── ssh_client.py       # 封装的 SSH 客户端
```

## 使用步骤
1. 确认Python依赖安装
```
pip install logbook requests PyMySQL PyYAML
```
2. 配置文件
*  在 configs/ 目录下，根据环境修改以下 YAML 文件：​
*  app_config.yaml: 填入飞书 Webhook URL和数据库连接信息。​
*  nodes.yaml: 添加巡检的服务器列表。​
*  thresholds.yaml: 根据需要调整各项检查的告警阈值。​
*  profiles.yaml: 如果想创建新的巡检策略，可以在此定义。

3. 运行巡检
```
# 运行对所有已定义节点的默认巡检
python gpu-node-checker.py

# 只对特定节点进行巡检
python gpu-node-checker.py --hosts 10.1.3.23,node201
```

4. 如果需要添加新检查项
* 定义告警模型（core/modles.py)​:
    * 在文件顶部添加新的告警类型常量，如 TYPE_NEW_CHECK = "system.new_check"​
    * 在 ALERT_METADATA 字典中，为这个新类型添加条目，定义其告警级别、标题和群组​
* 实现检查逻辑 (在 checks/ 目录下):​
    * 在合适的文件中（如 system_checks.py），创建两个函数：​
    * get_new_check_command(): 返回要在远程节点上执行的 shell 命令。​
    * parse_new_check_result(): 接收命令执行结果，并根据结果返回一个成功或失败的字典。​
* 在 Profile 中使用 (configs/profiles.yaml):​
* 将新检查项的名称（如 system.new_check）添加到希望运行的 profile 中。