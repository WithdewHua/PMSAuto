#!/bin/bash
# STRM文件自动生成脚本
# 描述: 批量生成不同媒体类型的STRM文件

set -euo pipefail  # 严格模式：遇到错误退出，未定义变量报错，管道命令失败时退出

# 定义常量
readonly SCRIPT_DIR="/opt/PMSAuto"
readonly PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python3"
readonly STRM_SCRIPT="${SCRIPT_DIR}/src/auto_strm/auto_strm.py"

# 默认参数值
DEFAULT_SCAN_THREADS=""  # 空表示不传入参数，使用程序默认值
DEFAULT_WORKERS=""       # 空表示使用默认值（CPU核心数）
DEFAULT_INTERACTIVE=""   # 默认非交互式
DEFAULT_PLEX_SCAN=""     # 默认不启用 Plex 扫描

# 颜色定义
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

# 显示帮助信息
show_help() {
    cat << EOF
使用方法: $0 [选项]

选项:
  -s, --scan-threads NUM    扫描远程文件夹的最大线程数，默认不指定
  -w, --workers NUM         文件处理的最大线程数，默认为CPU核心数
  -i, --interactive         启用交互式模式，在关键阶段询问是否继续
  -p, --plex-scan           启用 Plex 差集扫描功能
  -h, --help               显示此帮助信息

示例:
  $0                       # 使用默认参数
  $0 -s 2                  # 使用2个线程扫描文件夹
  $0 -w 8                  # 使用8个线程处理文件
  $0 -s 3 -w 16            # 使用3个线程扫描，16个线程处理文件
  $0 -i                    # 启用交互式模式
  $0 -p                    # 启用 Plex 差集扫描
  $0 -s 2 -i -p            # 使用2个线程扫描，启用交互式模式和 Plex 扫描

EOF
}

# 解析命令行参数
parse_args() {
    SCAN_THREADS="$DEFAULT_SCAN_THREADS"
    WORKERS="$DEFAULT_WORKERS"
    INTERACTIVE="$DEFAULT_INTERACTIVE"
    PLEX_SCAN="$DEFAULT_PLEX_SCAN"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            -s|--scan-threads)
                if [[ -n "${2:-}" && "$2" =~ ^[0-9]+$ ]]; then
                    SCAN_THREADS="$2"
                    shift 2
                else
                    log_error "选项 $1 需要一个数字参数"
                    exit 1
                fi
                ;;
            -w|--workers)
                if [[ -n "${2:-}" && "$2" =~ ^[0-9]+$ ]]; then
                    WORKERS="$2"
                    shift 2
                else
                    log_error "选项 $1 需要一个数字参数"
                    exit 1
                fi
                ;;
            -i|--interactive)
                INTERACTIVE="1"
                shift
                ;;
            -p|--plex-scan)
                PLEX_SCAN="1"
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                log_error "未知选项: $1"
                show_help
                exit 1
                ;;
        esac
    done
}

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1" >&2
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# 检查环境函数
check_environment() {
    log_info "检查环境..."
    
    if [[ ! -d "$SCRIPT_DIR" ]]; then
        log_error "脚本目录不存在: $SCRIPT_DIR"
        exit 1
    fi
    
    if [[ ! -f "$PYTHON_BIN" ]]; then
        log_error "Python解释器不存在: $PYTHON_BIN"
        exit 1
    fi
    
    if [[ ! -f "$STRM_SCRIPT" ]]; then
        log_error "STRM脚本不存在: $STRM_SCRIPT"
        exit 1
    fi
    
    log_success "环境检查通过"
}

# 执行STRM生成函数 - 批量处理
run_strm_batch() {
    local configs=("$@")
    local cmd_args=("-f" "${configs[@]}")
    
    # 添加扫描线程数参数
    if [[ -n "$SCAN_THREADS" ]]; then
        cmd_args+=("--scan-threads" "$SCAN_THREADS")
        log_info "使用扫描线程数: $SCAN_THREADS"
    else
        log_info "使用默认扫描模式: 程序默认值"
    fi
    
    # 添加文件处理线程数参数
    if [[ -n "$WORKERS" ]]; then
        cmd_args+=("-w" "$WORKERS")
        log_info "使用文件处理线程数: $WORKERS"
    else
        log_info "使用默认文件处理线程数: CPU核心数"
    fi
    
    # 添加交互式参数
    if [[ -n "$INTERACTIVE" ]]; then
        cmd_args+=("--interactive")
        log_info "启用交互式模式"
    fi
    
    # 添加 Plex 扫描参数
    if [[ -n "$PLEX_SCAN" ]]; then
        cmd_args+=("--plex-scan")
        log_info "启用 Plex 差集扫描功能"
    fi
    
    log_info "开始批量处理 ${#configs[@]} 个配置..."
    for config in "${configs[@]}"; do
        log_info "  - $config"
    done
    
    log_info "执行命令: $PYTHON_BIN $STRM_SCRIPT ${cmd_args[*]}"
    
    if "$PYTHON_BIN" "$STRM_SCRIPT" "${cmd_args[@]}"; then
        log_success "批量处理完成，共处理 ${#configs[@]} 个配置"
        return 0
    else
        log_error "批量处理失败"
        return 1
    fi
}

# 主函数
main() {
    local start_time=$(date +%s)
    local failed_count=0
    local success_count=0
    
    # 解析命令行参数
    parse_args "$@"
    
    log_info "开始STRM文件生成任务..."
    
    # 检查环境
    check_environment
    
    # 切换到工作目录
    if ! cd "$SCRIPT_DIR"; then
        log_error "无法切换到工作目录: $SCRIPT_DIR"
        exit 1
    fi
    
    # 定义任务配置数组 (source:category:target)
    local -a configs=(
        "GD-TVShows2:TVShows:/Media2"
        "GD-TVShows2:VarietyShows:/Media2"
        "GD-TVShows2:Documentary:/Media2"
        "GD-Anime:Anime:/Media"
        "GD-Movies-2:Movies:/Media"
        "GD-Movies-2:NC17-Movies:/Media"
        "GD-Movies-2:Concerts:/Media"
        "GD-NSFW-2:NSFW:/Media"
    )
    
    # 批量执行所有任务
    set +e
    if run_strm_batch "${configs[@]}"; then
        success_count=${#configs[@]}
        failed_count=0
    else
        success_count=0
        failed_count=${#configs[@]}
    fi
    set -e
    
    # 输出执行结果
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo
    log_info "========== 执行结果 =========="
    log_info "总任务数: ${#configs[@]}"
    log_info "成功: $success_count"
    if [[ $failed_count -gt 0 ]]; then
        log_info "失败: $failed_count"
    else
        log_info "失败: $failed_count"
    fi
    log_info "执行时间: ${duration}秒"
    log_info "============================="
    
    # 根据失败数量返回退出码
    if [[ $failed_count -gt 0 ]]; then
        log_warn "有任务执行失败，请检查日志"
        exit 1
    else
        log_success "所有任务执行成功！"
        exit 0
    fi
}

# 脚本入口点
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
