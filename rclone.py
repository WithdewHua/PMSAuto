import os
import json
import time
import psutil
import subprocess

import filelock

from logging.handlers import RotatingFileHandler
from log import logger, logFormatter


# ------------配置项开始------------------

# Rclone运行命令相关
src_path = "/home/tomove"
dest_path = "GoogleDrive:/tmp"
rclone_log_file = "/tmp/rclone.log"

# 检查rclone间隔 (s)
check_after_start = 60  # 在拉起rclone进程后，休息xxs后才开始检查rclone状态，防止 rclone rc core/stats 报错退出
check_interval = 10  # 主进程每次进行rclone rc core/stats检查的间隔

# 本脚本临时文件
instance_lock_path = r"/tmp/autorclone.lock"
instance_config_path = r"/tmp/autorclone.conf"

# 本脚本运行日志
script_log_file = r"/tmp/autorclone.log"

# ------------配置项结束------------------

if script_log_file:
    fileHandler = RotatingFileHandler(
        filename=script_log_file,
        mode="a",
        backupCount=2,
        maxBytes=5 * 1024 * 1024,
        encoding=None,
        delay=False,
    )
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)


def write_config(instance_config, name, value):
    instance_config[name] = value
    with open(instance_config_path, "w") as f:
        json.dump(instance_config, f, sort_keys=True)


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


def auto_rclone(src_path, dest_path):
    # 运行变量
    instance_config = {}

    # 单例模式
    instance_check = filelock.FileLock(instance_lock_path)
    with instance_check.acquire(timeout=0):
        # 加载instance配置
        if os.path.exists(instance_config_path):
            logger.info("Instance config exist, Load it...")
            config_raw = open(instance_config_path).read()
            instance_config = json.loads(config_raw)

        # 对上次记录的pid信息进行检查
        if "last_pid" in instance_config:
            last_pid = instance_config.get("last_pid")
            logger.debug("Last PID exist, Start to check if it is still alive")
            force_kill_rclone_subproc_by_parent_pid(last_pid)

        cmd_rclone = f'rclone copy "{src_path}" "{dest_path}" --rc --drive-server-side-across-configs -v --log-file {rclone_log_file}'

        # 起一个subprocess调rclone
        proc = subprocess.Popen(cmd_rclone, shell=True)

        # 等待，以便rclone完全起起来
        logger.info(
            "Wait %s seconds to full call rclone command: %s"
            % (check_after_start, cmd_rclone)
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
        while True:
            try:
                response = subprocess.check_output("rclone rc core/stats", shell=True)
            except subprocess.CalledProcessError as error:
                cnt_error = cnt_error + 1
                err_msg = "check core/stats failed for %s times," % cnt_error
                if cnt_error > 3:
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

            time.sleep(check_interval)


if __name__ == "__main__":
    auto_rclone(src_path=src_path, dest_path=dest_path)
