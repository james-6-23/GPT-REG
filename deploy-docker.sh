#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_ROOT="/Server/Docker/reg-gpt"
HOST_CONFIG_DIR="${HOST_ROOT}/config"
HOST_LOG_DIR="${HOST_ROOT}/logs"
HOST_STATE_DIR="${HOST_ROOT}/state"
HOST_DATA_DIR="${HOST_ROOT}/data"
HOST_TOKEN_DIR="${HOST_DATA_DIR}/Token-OpenAi"
HOST_CONFIG_PATH="${HOST_CONFIG_DIR}/reg_config.toml"
ACTION="${1:-up}"
COMPOSE_CMD=()

log() {
  printf '[reg-gpt-docker] %s\n' "$1"
}

die() {
  printf '[reg-gpt-docker] %s\n' "$1" >&2
  exit 1
}

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
    return
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
    return
  fi
  die "未检测到 docker compose，请先安装 Docker Compose 插件或 docker-compose。"
}

ensure_prerequisites() {
  command -v docker >/dev/null 2>&1 || die "未检测到 docker 命令，请先安装 Docker。"
  detect_compose
}

compose() {
  "${COMPOSE_CMD[@]}" -f "${SCRIPT_DIR}/docker-compose.yml" "$@"
}

migrate_legacy_layout() {
  if [ -f "${HOST_ROOT}/reg_config.toml" ] && [ ! -f "${HOST_CONFIG_PATH}" ]; then
    mv "${HOST_ROOT}/reg_config.toml" "${HOST_CONFIG_PATH}"
    log "已迁移旧配置文件到 ${HOST_CONFIG_PATH}"
  fi
  if [ -f "${HOST_ROOT}/runtime.log" ] && [ ! -f "${HOST_LOG_DIR}/runtime.log" ]; then
    mv "${HOST_ROOT}/runtime.log" "${HOST_LOG_DIR}/runtime.log"
    log "已迁移旧运行日志到 ${HOST_LOG_DIR}/runtime.log"
  fi
  if [ -f "${HOST_ROOT}/runtime_state.json" ] && [ ! -f "${HOST_STATE_DIR}/runtime_state.json" ]; then
    mv "${HOST_ROOT}/runtime_state.json" "${HOST_STATE_DIR}/runtime_state.json"
    log "已迁移旧运行状态到 ${HOST_STATE_DIR}/runtime_state.json"
  fi
  if [ -f "${HOST_ROOT}/cpa_state.json" ] && [ ! -f "${HOST_STATE_DIR}/cpa_state.json" ]; then
    mv "${HOST_ROOT}/cpa_state.json" "${HOST_STATE_DIR}/cpa_state.json"
    log "已迁移旧 CPA 状态到 ${HOST_STATE_DIR}/cpa_state.json"
  fi
  if [ -d "${HOST_ROOT}/Token-OpenAi" ] && [ ! -d "${HOST_TOKEN_DIR}" ]; then
    mv "${HOST_ROOT}/Token-OpenAi" "${HOST_TOKEN_DIR}"
    log "已迁移旧 Token 目录到 ${HOST_TOKEN_DIR}"
  fi
}

prepare_host_root() {
  mkdir -p "${HOST_CONFIG_DIR}" "${HOST_LOG_DIR}" "${HOST_STATE_DIR}" "${HOST_DATA_DIR}"
  migrate_legacy_layout
  mkdir -p "${HOST_TOKEN_DIR}"

  if [ ! -f "${HOST_CONFIG_PATH}" ]; then
    cp "${SCRIPT_DIR}/reg_config.example.toml" "${HOST_CONFIG_PATH}"
    log "已初始化配置文件：${HOST_CONFIG_PATH}"
  fi
}

read_webui_port() {
  local port
  port="$(awk '
    /^\[webui\]/ { in_section=1; next }
    /^\[/ && in_section { exit }
    in_section && $1 ~ /^port$/ {
      gsub(/[[:space:]]/, "", $0)
      split($0, pair, "=")
      print pair[2]
      exit
    }
  ' "${HOST_CONFIG_PATH}")"

  if [[ "${port}" =~ ^[0-9]+$ ]] && [ "${port}" -ge 1 ] && [ "${port}" -le 65535 ]; then
    printf '%s\n' "${port}"
    return
  fi

  printf '25666\n'
}

start_service() {
  prepare_host_root
  log "开始构建并启动容器"
  compose up -d --build
  log "部署完成。"
  log "宿主机运行目录：${HOST_ROOT}"
  log "网络模式：host"
  log "当前端口：$(read_webui_port)（已从 ${HOST_CONFIG_PATH} 读取）"
  log "容器仅挂载 runtime 目录，不再把源码同步到宿主机。"
  log "若安全凭据未手动配置，可执行 docker logs reg-gpt 查看首次生成的凭据。"
}

stop_service() {
  log "停止并删除容器"
  compose down
}

restart_service() {
  prepare_host_root
  log "重建并重启容器"
  compose up -d --build --force-recreate
}

show_status() {
  compose ps
}

show_logs() {
  compose logs -f --tail=200
}

show_usage() {
  cat <<'EOF'
用法：
  ./deploy-docker.sh up       构建并启动容器（默认）
  ./deploy-docker.sh restart  重建并重启容器
  ./deploy-docker.sh down     停止并删除容器
  ./deploy-docker.sh logs     查看容器日志
  ./deploy-docker.sh ps       查看容器状态

说明：
  1. 本脚本面向 Linux 宿主机，默认宿主机运行目录固定为 /Server/Docker/reg-gpt
  2. 容器不传递任何环境变量，业务配置统一使用 /Server/Docker/reg-gpt/config/reg_config.toml
  3. 当前使用 host 网络，默认 WebUI 端口为 25666
  4. 运行日志、状态文件、Token 结果都会落在 /Server/Docker/reg-gpt 下的独立子目录
EOF
}

main() {
  ensure_prerequisites

  case "${ACTION}" in
    up)
      start_service
      ;;
    restart)
      restart_service
      ;;
    down)
      stop_service
      ;;
    logs)
      show_logs
      ;;
    ps)
      show_status
      ;;
    *)
      show_usage
      exit 1
      ;;
  esac
}

main "$@"
