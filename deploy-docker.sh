#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-up}"
COMPOSE_CMD=()

log() {
  printf '[reg-gpt] %s\n' "$1"
}

die() {
  printf '[reg-gpt] %s\n' "$1" >&2
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

prepare() {
  # 创建数据目录
  mkdir -p "${SCRIPT_DIR}/data/tokens"
  mkdir -p "${SCRIPT_DIR}/data/logs"

  # 首次部署：从模板创建配置文件
  if [ ! -f "${SCRIPT_DIR}/config.toml" ]; then
    cp "${SCRIPT_DIR}/reg_config.example.toml" "${SCRIPT_DIR}/config.toml"
    log "已创建配置文件：${SCRIPT_DIR}/config.toml"
  fi
}

start_service() {
  prepare
  log "开始构建并启动容器"
  compose up -d --build
  log "部署完成。"
  log "配置文件：${SCRIPT_DIR}/config.toml"
  log "数据目录：${SCRIPT_DIR}/data/"
  log "网络模式：host"
}

stop_service() {
  log "停止并删除容器"
  compose down
}

restart_service() {
  prepare
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

目录结构：
  config.toml           配置文件（自动从模板创建）
  data/                 数据目录（挂载到容器）
    tokens/             注册成功的 Token 文件
    logs/               运行日志
    reg.db              SQLite 状态数据库
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
