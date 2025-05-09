import glob
import json
import logging
import os
import random
import re
import subprocess
import time
from logging.handlers import RotatingFileHandler

import filelock
import psutil
from settings import RC_ADDR

# ------------配置项开始------------------
# Account目录
sa_json_folder = (
    r"/root/.config/rclone/accounts"  # 绝对目录，最后没有 '/'，路径中不要有空格
)

# Rclone运行命令相关
# > 更新 rc 地址
if not RC_ADDR:
    rc_addr = f"localhost:{random.randint(5573, 5582)}"  # 随机端口
else:
    rc_addr = RC_ADDR if not re.match("^:", RC_ADDR) else f"localhost{RC_ADDR}"
src_path = "/home/tomove"
dest_path = "/tmp"
rclone_log_file = f"/tmp/rclone_{rc_addr}.log"

# 检查rclone间隔 (s)
check_after_start = 5  # 在拉起rclone进程后，休息xxs后才开始检查rclone状态，防止 rclone rc core/stats 报错退出
check_interval = 3  # 主进程每次进行rclone rc core/stats检查的间隔

# rclone帐号更换监测条件
switch_sa_level = 2  # 需要满足的规则条数，数字越大切换条件越严格，一定小于下面True（即启用）的数量，即 1 - 4(max)
switch_sa_rules = {
    "up_than_750": True,  # 当前帐号已经传过750G
    "error_user_rate_limit": True,  # Rclone 直接提示rate limit错误
    "zero_transferred_between_check_interval": True,  # 100次检查间隔期间rclone传输的量为0
    "all_transfers_in_zero": True,  # 当前所有transfers传输size均为0
}

# rclone帐号切换方法 (runtime or config)
# runtime 是修改启动rclone时附加的 `--drive-service-account-file` 参数
# config  是修改rclone的配置文件 `$HOME/.config/rclone/rclone.conf` ，此时你需要指定后面的rclone配置参数参数
switch_sa_way = "runtime"

# rclone配置参数 （当且仅当 switch_sa_way 为 `config` 时使用，且需要修改）
rclone_config_path = "/root/.config/rclone/rclone.conf"  # Rclone 配置文件位置
rclone_dest_name = (
    "GoogleDrive"  # Rclone目的地名称（与cmd_rclone中对应相同，并保证SA均已添加）
)

# 本脚本临时文件
# > 文件锁
instance_lock_path = f"/tmp/autorclone_{rc_addr}.lock"
instance_config_path = f"/tmp/autorclone_{rc_addr}.conf"

# 本脚本运行日志
script_log_file = f"/tmp/autorclone_{rc_addr}.log"
logging_datefmt = "%m/%d/%Y %H:%M:%S"
logging_format = "[%(asctime)s][%(levelname)s]<%(funcName)s>: %(message)s"

# ------------配置项结束------------------

# 日志相关
logFormatter = logging.Formatter(fmt=logging_format, datefmt=logging_datefmt)

logger = logging.getLogger()
logger.setLevel(logging.NOTSET)
while logger.handlers:  # Remove un-format logging in Stream, or all of messages are appearing more than once.
    logger.handlers.pop()

if script_log_file:
    fileHandler = RotatingFileHandler(
        filename=script_log_file,
        mode="a",
        backupCount=2,
        maxBytes=5 * 1024 * 1024,
        encoding=None,
        delay=0,
    )
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)

consoleHandler = logging.StreamHandler()
consoleHandler.setFormatter(logFormatter)
logger.addHandler(consoleHandler)


def write_config(instance_config, name, value):
    instance_config[name] = value
    with open(instance_config_path, "w") as f:
        json.dump(instance_config, f, sort_keys=True)


# 获得下一个Service Account Credentials JSON file path
def get_next_sa_json_path(sa_jsons, _last_sa):
    if _last_sa not in sa_jsons:  # 空字符串或者错误的sa_json_path，从头开始取
        next_sa_index = 0
    else:
        _last_sa_index = sa_jsons.index(_last_sa)
        next_sa_index = _last_sa_index + 1
    # 超过列表长度从头开始取
    if next_sa_index > len(sa_jsons):
        next_sa_index = next_sa_index - len(sa_jsons)
    return sa_jsons[next_sa_index]


# def switch_sa_by_config(cur_sa):
#     # 获得rclone配置
#     config = configparser.ConfigParser()
#     config.read(rclone_config_path)
#
#     if rclone_dest_name not in config:
#         logger.critical('Can\'t find section %s in your rclone.conf (path: %s)', (rclone_dest_name, rclone_config_path))
#         exit(1)
#
#     # 更改SA信息
#     sa_in_config = config[rclone_dest_name].get('service_account_file', '')
#     config[rclone_dest_name]['service_account_file'] = cur_sa
#     logger.info('Change rclone.conf SA information from %s to %s' % (sa_in_config, cur_sa))
#
#     # 保存
#     with open(rclone_config_path, 'w') as configfile:
#         config.write(configfile)
#
#     logger.info('Change SA information in rclone.conf Success')
#


def get_email_from_sa(sa):
    return json.load(open(sa, "r"))["client_email"]


# 强行杀掉Rclone
def force_kill_rclone_subproc_by_parent_pid(sh_pid):
    if psutil.pid_exists(sh_pid):
        sh_proc = psutil.Process(sh_pid)
        logger.info(
            "Get The Process information - pid: %s, name: %s" % (sh_pid, sh_proc.name())
        )
        for child_proc in sh_proc.children():
            if child_proc.name().find("rclone") > -1:
                logger.info(
                    "Force Killed rclone process which pid: %s" % child_proc.pid
                )
                child_proc.kill()


def auto_rclone(src_path, dest_path, files_from=None, action="copy"):
    # 运行变量
    instance_config = {}
    sa_jsons = []

    # 单例模式
    instance_check = filelock.FileLock(instance_lock_path)
    with instance_check.acquire(timeout=0):
        # 加载account信息
        sa_jsons = glob.glob(os.path.join(sa_json_folder, "*.json"))
        if len(sa_jsons) == 0:
            logger.error("No Service Account Credentials JSON file exists.")
            return False

        # 加载instance配置
        if os.path.exists(instance_config_path):
            logger.info(f"Instance config {instance_config_path} exist, Load it...")
            config_raw = open(instance_config_path).read()
            instance_config = json.loads(config_raw)

        # 对上次记录的pid信息进行检查
        if "last_pid" in instance_config:
            last_pid = instance_config.get("last_pid")
            logger.debug(
                f"Last PID {last_pid} exist, Start to check if it is still alive"
            )
            force_kill_rclone_subproc_by_parent_pid(last_pid)

        # 对上次记录的sa信息进行检查，如果有的话，重排sa_jsons
        # 这样我们就每次都从一个新的750G开始了
        last_sa = instance_config.get("last_sa", "")
        if last_sa in sa_jsons:
            logger.info(f"Get `last_sa` {last_sa} from config, resort list `sa_jsons`")
            last_sa_index = sa_jsons.index(last_sa)
            sa_jsons = sa_jsons[last_sa_index:] + sa_jsons[:last_sa_index]

        cmd_rclone = f'rclone {action} "{src_path}" "{dest_path}" --rc --drive-server-side-across-configs -v --log-file {rclone_log_file} --rc-addr {rc_addr}'
        if files_from:
            cmd_rclone += f" --files-from {files_from}"
        if action == "move":
            cmd_rclone += " --delete-empty-src-dirs"

        # 帐号切换循环
        while True:
            logger.info("Switch to next SA..........")
            last_sa = current_sa = get_next_sa_json_path(sa_jsons, last_sa)
            write_config(instance_config, "last_sa", current_sa)
            logger.info(
                "Get SA information, file: %s , email: %s"
                % (current_sa, get_email_from_sa(current_sa))
            )

            # 切换Rclone运行命令
            if switch_sa_way == "config":
                # switch_sa_by_config(current_sa)
                cmd_rclone_current_sa = cmd_rclone
            else:
                # 默认情况视为`runtime`，附加'--drive-service-account-file'参数
                cmd_rclone_current_sa = (
                    cmd_rclone + " --drive-service-account-file %s" % (current_sa,)
                )

            # 起一个subprocess调rclone
            proc = subprocess.Popen(cmd_rclone_current_sa, shell=True)

            # 等待，以便rclone完全起起来
            logger.info(
                "Wait %s seconds to full call rclone command: %s"
                % (check_after_start, cmd_rclone_current_sa)
            )
            time.sleep(check_after_start)

            # 记录pid信息
            # 注意，因为subprocess首先起sh，然后sh再起rclone，所以此处记录的实际是sh的pid信息
            # proc.pid + 1 在一般情况下就是rclone进程的pid，但不确定
            # 所以一定要用 force_kill_rclone_subproc_by_parent_pid(sh_pid) 方法杀掉rclone
            write_config(instance_config, "last_pid", proc.pid)
            logger.info("Run Rclone command Success in pid %s" % (proc.pid + 1))

            # 主进程使用 `rclone rc core/stats` 检查子进程情况
            cnt_error = 0
            cnt_403_retry = 0
            cnt_transfer_last = 0
            while True:
                try:
                    response = subprocess.check_output(
                        f"rclone rc core/stats --url http://{rc_addr}", shell=True
                    )
                except subprocess.CalledProcessError:
                    cnt_error = cnt_error + 1
                    err_msg = "check core/stats failed for %s times," % cnt_error
                    if cnt_error >= 3:
                        logger.error(
                            err_msg + " Force kill exist rclone process %s." % proc.pid
                        )
                        proc.kill()
                        return False

                    logger.warning(
                        err_msg + " Wait %s seconds to recheck." % check_interval
                    )
                    time.sleep(check_interval)
                    continue  # 重新检查
                else:
                    cnt_error = 0

                # 解析 `rclone rc core/stats` 输出
                response_json = json.loads(response.decode("utf-8").replace("\0", ""))
                cnt_transfer = response_json.get("bytes", 0)

                # 输出当前情况
                logger.info(
                    "Transfer Status - Upload: %s GiB, Avg upspeed: %s MiB/s, Transfered: %s, ETA: %s."
                    % (
                        response_json.get("bytes", 0) / pow(1024, 3),
                        response_json.get("speed", 0) / pow(1024, 2),
                        response_json.get("transfers", 0),
                        response_json.get("eta", 0),
                    )
                )

                # 判断是否应该进行切换
                should_switch = 0
                switch_reason = "Switch Reason: "

                # 检查当前总上传是否超过 750 GB
                if switch_sa_rules.get("up_than_750", False):
                    if cnt_transfer > 750 * pow(1000, 3):  # 这里是 750GB 而不是 750GiB
                        should_switch += 1
                        switch_reason += "Rule `up_than_750` hit, "

                # 检查监测期间rclone传输的量
                if switch_sa_rules.get(
                    "zero_transferred_between_check_interval", False
                ):
                    if cnt_transfer - cnt_transfer_last == 0:  # 未增加
                        cnt_403_retry += 1
                        if cnt_403_retry % 10 == 0:
                            logger.warning(
                                "Rclone seems not transfer in %s checks" % cnt_403_retry
                            )
                        if cnt_403_retry >= 100:  # 超过100次检查均未增加
                            should_switch += 1
                            switch_reason += (
                                "Rule `zero_transferred_between_check_interval` hit, "
                            )
                    else:
                        cnt_403_retry = 0
                    cnt_transfer_last = cnt_transfer

                # Rclone 直接提示错误403 ratelimitexceed
                if switch_sa_rules.get("error_user_rate_limit", False):
                    last_error = response_json.get("lastError", "")
                    if last_error.find("userRateLimitExceeded") > -1:
                        should_switch += 1
                        switch_reason += "Rule `error_user_rate_limit` hit, "

                # 检查当前transferring的传输量
                if switch_sa_rules.get("all_transfers_in_zero", False):
                    graceful = True
                    if response_json.get("transferring", False):
                        for transfer in response_json["transferring"]:
                            # 处理`bytes`或者`speed`不存在的情况（认为该transfer已经完成了） @yezi1000
                            if "bytes" not in transfer or "speed" not in transfer:
                                continue
                            elif (
                                transfer.get("bytes", 0) != 0
                                and transfer.get("speed", 0) > 0
                            ):  # 当前还有未完成的传输
                                graceful = False
                                break
                    if graceful:
                        should_switch += 1
                        switch_reason += "Rule `all_transfers_in_zero` hit, "

                # 大于设置的更换级别
                if should_switch >= switch_sa_level:
                    logger.info(
                        "Transfer Limit may hit (%s), Try to Switch.........."
                        % switch_reason
                    )
                    force_kill_rclone_subproc_by_parent_pid(
                        proc.pid
                    )  # 杀掉当前rclone进程
                    break  # 退出主进程监测循环，从而切换到下一个帐号

                time.sleep(check_interval)


if __name__ == "__main__":
    auto_rclone(src_path=src_path, dest_path=dest_path)
