#!/bin/bash

# 行业信息助手 - 一键启动脚本
# 用法: ./start-services.sh [command]
# 命令: start | stop | restart | status | logs

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Reuse the backend's local credentials without embedding them in Compose.
compose() {
    docker compose --env-file "$SCRIPT_DIR/backend/.env" "$@"
}

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Docker 是否运行
check_docker() {
    if ! command -v docker > /dev/null 2>&1; then
        log_error "未找到 Docker，请先安装 Docker Engine 或启用 Docker Desktop 的 WSL 集成"
        exit 1
    fi
    if ! docker info > /dev/null 2>&1; then
        log_error "无法连接 Docker，请启动 WSL 中的 Docker 服务或 Docker Desktop"
        exit 1
    fi
    if ! docker compose version > /dev/null 2>&1; then
        log_error "未找到 Docker Compose 插件，请安装支持 docker compose 的版本"
        exit 1
    fi
    log_success "Docker 运行正常"
}

# 启动中间件服务
start_services() {
    log_info "正在启动中间件服务 (PostgreSQL, Redis, Milvus, Elasticsearch)..."
    log_info "等待全部 6 个容器健康就绪（最长 180 秒，不含镜像下载时间）..."
    if ! compose up -d --wait --wait-timeout 180; then
        log_error "服务未全部就绪，请查看上方错误及 ./start-services.sh logs [服务名]"
        compose ps -a
        return 1
    fi

    # 检查服务状态
    check_service_health

    log_success "所有中间件服务已启动!"
    echo ""
    echo "服务访问地址:"
    echo "  - PostgreSQL: localhost:15432"
    echo "  - Redis: localhost:16379"
    echo "  - Milvus: localhost:29530 (健康检查: localhost:19091)"
    echo "  - Elasticsearch: localhost:1200"
    echo "  - MinIO API: localhost:19000"
    echo "  - MinIO Console: localhost:19001 (minioadmin/minioadmin)"
    echo ""
    log_info "现在可以启动前后端服务了"
    echo "  - 后端: cd backend && python app/app_main.py"
    echo "  - 前端: cd frontend && npm run dev"
}

# 停止服务
stop_services() {
    log_info "正在停止所有中间件服务..."
    compose down
    log_success "所有服务已停止"
}

# 重启服务
restart_services() {
    stop_services
    sleep 2
    start_services
}

# 检查服务健康状态
check_service_health() {
    log_info "检查服务健康状态..."
    local service container_id state failed=0
    for service in postgres redis etcd minio milvus elasticsearch; do
        container_id=$(compose ps -a -q "$service") || return 1
        if [ -z "$container_id" ]; then
            log_warning "$service: 未创建"
            failed=1
            continue
        fi
        state=$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "$container_id") || return 1
        if [ "$state" = "running/healthy" ]; then
            log_success "$service: 健康"
        else
            log_warning "$service: $state"
            failed=1
        fi
    done
    return "$failed"
}

# 查看服务状态
show_status() {
    log_info "服务状态:"
    compose ps -a
    echo ""
    check_service_health
}

# 查看日志
show_logs() {
    if [ -z "${2:-}" ]; then
        compose logs -f --tail=100
    else
        compose logs -f --tail=100 "$2"
    fi
}

# 清理数据（危险操作）
clean_data() {
    log_warning "警告: 此操作将删除所有数据，包括数据库、缓存和向量数据!"
    read -p "确定要继续吗? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        stop_services
        compose down -v
        log_success "所有数据已清理"
    else
        log_info "操作已取消"
    fi
}

# 显示帮助
show_help() {
    echo "行业信息助手 - 服务管理脚本"
    echo ""
    echo "用法: $0 [命令]"
    echo ""
    echo "命令:"
    echo "  start    启动所有中间件服务"
    echo "  stop     停止所有服务"
    echo "  restart  重启所有服务"
    echo "  status   查看服务状态"
    echo "  logs     查看服务日志 (可选: logs [服务名])"
    echo "  clean    清理所有数据 (危险!)"
    echo "  help     显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 start          # 启动服务"
    echo "  $0 logs postgres  # 查看 PostgreSQL 日志"
}

# 服务管理命令都需要同一个 Docker Compose 插件。
case "${1:-help}" in
    start|stop|restart|status|logs|clean) check_docker ;;
esac

# 主逻辑
case "${1:-help}" in
    start)
        start_services
        ;;
    stop)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "$@"
        ;;
    clean)
        clean_data
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
