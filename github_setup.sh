#!/bin/bash
# GitHub 自动部署脚本
# 用法: bash github_setup.sh <你的GitHub用户名> <你的GitHub_TOKEN>
# 
# TOKEN 获取方法:
# 1. 打开 https://github.com/settings/tokens
# 2. 点击 "Generate new token (classic)"
# 3. 勾选 "repo" 权限
# 4. 生成，把token复制下来粘贴进来

set -e
REPO_NAME="auto_trader"
GITHUB_USER=${1:-""}
GITHUB_TOKEN=${2:-""}

if [ -z "$GITHUB_USER" ] || [ -z "$GITHUB_TOKEN" ]; then
    echo "用法: bash github_setup.sh <GitHub用户名> <GitHub_TOKEN>"
    echo ""
    echo "TOKEN 获取方法:"
    echo "1. 打开 https://github.com/settings/tokens"
    echo "2. 点击 Generate new token (classic)"
    echo "3. 勾选 repo 权限"
    echo "4. 生成后粘贴进来"
    echo ""
    echo "或者直接在浏览器打开这个链接创建:"
    echo "https://github.com/settings/tokens/new?scopes=repo&description=auto_trader+EXE+build"
    exit 1
fi

echo "=== GitHub 自动部署设置 ==="
echo "用户名: $GITHUB_USER"
echo "仓库: $REPO_NAME"

# 初始化 git（如果还没有）
if [ ! -d .git ]; then
    git init
    git add .
    git commit -m "Initial commit: auto_trader T+0 system"
fi

# 尝试创建远程仓库
RESPONSE=$(curl -s -X POST \
    -H "Authorization: token $GITHUB_TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    https://api.github.com/user/repos \
    -d "{\"name\":\"$REPO_NAME\",\"private\":false,\"description\":\"云图控股T+0自动做T工具 Windows EXE\",\"auto_init\":false}")

if echo "$RESPONSE" | grep -q '"id"'; then
    echo "✅ 仓库创建成功"
elif echo "$RESPONSE" | grep -q '"Already exists"'; then
    echo "⚠️  仓库已存在，继续推送"
else
    echo "⚠️  创建仓库响应: $RESPONSE"
fi

# 添加远程并推送
git remote remove origin 2>/dev/null || true
git remote add origin "https://${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"
git branch -M main
git push -u origin main

echo ""
echo "✅ 代码推送成功！"
echo ""
echo "=== 现在等待 GitHub Actions 自动构建（约5-10分钟） ==="
echo "1. 打开 https://github.com/$GITHUB_USER/$REPO_NAME/actions"
echo "2. 等待 'Build Windows EXE' 任务完成（绿色勾✓）"
echo "3. 点击该任务 → Artifacts → 下载 auto_trader_windows_exe"
echo ""
echo "下载的 EXE 就是真正的跨Windows通用版本，复制到任何电脑直接双击跑！"
