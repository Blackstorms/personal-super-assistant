#!/usr/bin/env bash
# 飞书用户 OAuth（方案一：与 @larksuiteoapi/lark-mcp login 同源）
# 推荐：在桌面端 插件市场 → 连接器 → 飞书 →「浏览器授权获取 USER_ACCESS_TOKEN」
#
# 命令行备选（token 存在本机 lark-mcp 加密存储，PSA 内置工具仍需在 UI 点授权同步到 DB）：
#   lark-mcp login -a "$APP_ID" -s "$APP_SECRET"
#   # 或未预装时：npx -y @larksuiteoapi/lark-mcp login -a "$APP_ID" -s "$APP_SECRET"
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "请在 PSA 桌面端使用「浏览器授权」写入 USER_ACCESS_TOKEN。"
echo "或手动："
echo "  1. 开放平台 → 安全设置 → 重定向 URL 添加："
echo "     http://localhost:3000/callback"
echo "  2. 插件市场 → 连接器 → 飞书 → 填写 APP_ID/APP_SECRET → 浏览器授权"
echo ""
echo "CLI 登录（lark-mcp 本地缓存，不自动写入 PSA DB）："
echo "  lark-mcp login -a <APP_ID> -s <APP_SECRET>"
echo "  # 未预装时：npx -y @larksuiteoapi/lark-mcp login -a <APP_ID> -s <APP_SECRET>"
