#!/bin/bash
# STRM文件自动生成脚本
# 描述: 批量生成不同媒体类型的STRM文件

set -euo pipefail  # 严格模式：遇到错误退出，未定义变量报错，管道命令失败时退出

# 定义常量
readonly SCRIPT_DIR="/opt/PMSAuto"
readonly PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python3"
readonly STRM_SCRIPT="${SCRIPT_DIR}/src/auto_strm/auto_strm.py"

# 颜色定义
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly NC='\033[0m' # No Color

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

# 执行STRM生成函数
run_strm() {
    local source="$1"
    local category="$2"
    local target="$3"
    local config="${source}:${category}:${target}"
    
    log_info "开始处理: $config"
    
    if "$PYTHON_BIN" "$STRM_SCRIPT" -f "$config"; then
        log_success "完成处理: $config"
        return 0
    else
        log_error "处理失败: $config"
        return 1
    fi
}

# 主函数
main() {
    local start_time=$(date +%s)
    local failed_count=0
    local success_count=0
    
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
    
    # 执行所有任务
    for config in "${configs[@]}"; do
        IFS=':' read -r source category target <<< "$config"
        
        # 临时关闭 -e 模式，手动处理错误
        set +e
        if run_strm "$source" "$category" "$target"; then
            ((success_count++))
        else
            ((failed_count++))
        fi
        # 重新启用 -e 模式
        set -e
        
        # 添加短暂延迟避免过载
        sleep 1
    done
    
    # 输出执行结果
    local end_time=$(date +%s)
    local duration=$((end_time - start_time))
    
    echo
    log_info "========== 执行结果 =========="
    log_info "总任务数: ${#configs[@]}"
    log_success "成功: $success_count"
    if [[ $failed_count -gt 0 ]]; then
        log_error "失败: $failed_count"
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
