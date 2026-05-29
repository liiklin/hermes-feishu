#!/bin/bash
set -euo pipefail

# hermes-feishu-full — 一键安装脚本
# 在每台新机器上运行一次即可

REPO="${1:-你的用户名/hermes-feishu}"
echo "==> 安装插件: $REPO"
hermes plugins install "$REPO"

echo "==> 重启网关使 hook 生效"
hermes gateway restart

echo "==> 完成！首次重启可能需要几秒钟"
echo "    检查 hook 是否加载: grep 'card-wrapper' ~/.hermes/logs/gateway.log"
