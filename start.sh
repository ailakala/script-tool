#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# 首次运行：从模板创建 .env
if [ ! -f .env ]; then
    echo ">>> 首次运行：创建 .env 配置文件"
    cp .env.example .env
    echo ">>> 请编辑 .env 文件，填入你的 AI API Key，然后重新运行此脚本"
    exit 1
fi

# 安装依赖（如果需要）
if ! python -c "import fastapi" 2>/dev/null; then
    echo ">>> 安装依赖..."
    pip install -r requirements.txt
fi

echo ">>> 启动服务..."
echo ">>> 打开浏览器访问 http://localhost:8000"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
