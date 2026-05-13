#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/admin/hbj/libriscribe}"
APP_PORT="${APP_PORT:-8888}"
REPO_URL="${REPO_URL:-https://github.com/a872034547-cpu/hbj.git}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"

log() {
  printf '\n\033[1;32m[LibriScribe]\033[0m %s\n' "$*"
}

warn() {
  printf '\n\033[1;33m[提示]\033[0m %s\n' "$*"
}

fail() {
  printf '\n\033[1;31m[失败]\033[0m %s\n' "$*" >&2
  exit 1
}

if [[ "${EUID}" -ne 0 ]]; then
  fail "请使用 root 用户执行，或在命令前加 sudo。示例：sudo bash scripts/install_alibaba_linux3.sh"
fi

log "检测系统信息"
if [[ -f /etc/os-release ]]; then
  cat /etc/os-release
else
  warn "未找到 /etc/os-release，继续尝试安装。"
fi

log "安装系统依赖：Python、Git、编译工具、文档解析常用库"
dnf makecache -y || true
dnf install -y \
  python3 python3-pip python3-devel \
  git curl gcc gcc-c++ make \
  libffi-devel openssl-devel bzip2-devel zlib-devel xz-devel \
  poppler-utils tesseract tesseract-langpack-chi_sim \
  libjpeg-turbo-devel freetype-devel \
  firewalld || fail "系统依赖安装失败，请检查网络或 yum/dnf 源。"

log "检查 Python 版本"
${PYTHON_BIN} --version || fail "python3 不可用。"
${PYTHON_BIN} -m pip --version || ${PYTHON_BIN} -m ensurepip --upgrade || true

log "准备项目目录：${APP_DIR}"
mkdir -p "$(dirname "${APP_DIR}")"
if [[ -d "${APP_DIR}/.git" ]]; then
  log "检测到已有项目，执行 git pull 更新"
  git -C "${APP_DIR}" pull --ff-only || warn "git pull 失败，继续使用本地代码。"
elif [[ -f "${APP_DIR}/requirements.txt" && -d "${APP_DIR}/src/libriscribe" ]]; then
  log "检测到已有本地项目目录，跳过 clone"
else
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}" || fail "代码下载失败。可设置 REPO_URL 为你的私有仓库/镜像地址后重试。"
fi

cd "${APP_DIR}"

log "创建 Python 虚拟环境"
${PYTHON_BIN} -m venv .venv || fail "虚拟环境创建失败。"
source .venv/bin/activate

log "升级 pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel -i "${PIP_INDEX_URL}" || fail "pip 基础工具升级失败。"

log "安装项目依赖，时间可能较长"
python -m pip install -r requirements.txt -i "${PIP_INDEX_URL}" || fail "requirements.txt 依赖安装失败。"
python -m pip install -e . -i "${PIP_INDEX_URL}" || warn "pip install -e . 失败，但 Web 端可能仍可通过 PYTHONPATH=src 启动。"

log "写入一键启动脚本：${APP_DIR}/start_libriscribe.sh"
cat > "${APP_DIR}/start_libriscribe.sh" <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
cd "${APP_DIR}"
source .venv/bin/activate
export PYTHONPATH=src
python -m streamlit run src/libriscribe/web/app.py --server.address 0.0.0.0 --server.port ${APP_PORT}
EOF
chmod +x "${APP_DIR}/start_libriscribe.sh"

log "写入 systemd 服务：/etc/systemd/system/libriscribe.service"
cat > /etc/systemd/system/libriscribe.service <<EOF
[Unit]
Description=LibriScribe Streamlit Web UI
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PYTHONPATH=src
ExecStart=${APP_DIR}/.venv/bin/python -m streamlit run src/libriscribe/web/app.py --server.address 0.0.0.0 --server.port ${APP_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

log "开放防火墙端口 ${APP_PORT}（如果 firewalld 正在使用）"
systemctl enable --now firewalld >/dev/null 2>&1 || true
firewall-cmd --permanent --add-port=${APP_PORT}/tcp >/dev/null 2>&1 || true
firewall-cmd --reload >/dev/null 2>&1 || true

log "启动 LibriScribe 服务"
systemctl daemon-reload
systemctl enable --now libriscribe.service || fail "服务启动失败，请执行：journalctl -u libriscribe -n 100 --no-pager 查看日志。"

SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PUBLIC_IP="$(curl -fsS --connect-timeout 3 https://ifconfig.me 2>/dev/null || true)"

log "安装完成"
printf '\n访问地址（二选一）：\n'
printf '  内网地址：http://%s:%s\n' "${SERVER_IP:-服务器内网IP}" "${APP_PORT}"
printf '  公网地址：http://%s:%s\n' "${PUBLIC_IP:-你的服务器公网IP}" "${APP_PORT}"
printf '\n常用命令：\n'
printf '  查看状态：systemctl status libriscribe --no-pager\n'
printf '  查看日志：journalctl -u libriscribe -f\n'
printf '  重启服务：systemctl restart libriscribe\n'
printf '  手动启动：%s/start_libriscribe.sh\n\n' "${APP_DIR}"

warn "如果公网打不开，请到阿里云控制台 ECS 安全组放行 TCP ${APP_PORT} 端口。"
