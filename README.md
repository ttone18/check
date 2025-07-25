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
patrol_monitoring_system/
├── checks/                # 检查逻辑模块
│   ├── gpu_checks.py
│   ├── network_checks.py
│   └── system_checks.py
├── configs/               # 配置文件目录
│   ├── app_config.yaml    # 应用配置 (飞书, 数据库)
│   ├── nodes.yaml         # 节点列表
│   ├── profiles.yaml      # 巡检策略
│   └── thresholds.yaml    # 告警阈值
├── core/                  # 核心模块
│   ├── models.py          # 告警模型定义
│   └── notifier.py        # 告警发送器 (Feishu, MySQL)
├── main.py                # 主程序入口
└── requirements.txt       # Python 依赖
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