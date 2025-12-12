import os
import uuid
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# 下载保存目录（相对当前 app.py）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")

# 默认备份后缀
BACKUP_SUFFIXES = [
    ".bak", ".zip", ".rar", ".7z", ".tar", ".tar.gz", ".tgz",
    ".sql", ".db", ".old", ".backup"
]

# 默认字典路径（如果前端没传字典，就用这个）
DEFAULT_PATHS = [
    "index.php.bak",
    "index.jsp.bak",
    "config.php.bak",
    "wwwroot.zip",
    "website.zip",
    "backup.zip",
    "site_backup.zip",
    "db.sql",
    "backup.sql",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

# 任务缓存（内存中保存任务状态）
TASKS = {}
TASKS_LOCK = threading.Lock()


def looks_like_backup(url: str) -> bool:
    """简单根据 URL 后缀判断是否像备份文件"""
    lower = url.lower()
    return any(lower.endswith(s) for s in BACKUP_SUFFIXES)


def save_response_content(resp: requests.Response, save_path: str):
    """把响应内容以二进制流保存到本地文件"""
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            f.write(chunk)


def normalize_base_url(url: str) -> str:
    """补全协议、末尾加斜杠"""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
    if not url.endswith("/"):
        url += "/"
    return url


def log_line(task, msg: str):
    """往任务日志里追加一行"""
    with TASKS_LOCK:
        task["logs"].append(msg)


def update_target_status(task, index: int, **kwargs):
    """更新某个目标的状态/统计"""
    with TASKS_LOCK:
        for k, v in kwargs.items():
            task["targets"][index][k] = v


def scan_single_target(target_index: int, target: str, output_dir: str, paths: list, task):
    """扫描单个目标站点"""
    base_url = normalize_base_url(target)
    if not base_url:
        return

    update_target_status(task, target_index, status="scanning")

    log_line(task, f"\n===== 开始扫描：{base_url} =====")
    session = requests.Session()
    parsed = urlparse(base_url)
    host_tag = parsed.netloc.replace(":", "_")

    found_count = 0

    for path in paths:
        full_url = urljoin(base_url, path)
        try:
            log_line(task, f"[+] 测试：{full_url}")
            resp = session.get(
                full_url,
                headers=HEADERS,
                stream=True,
                timeout=15,
                allow_redirects=True,  # 跟随 301/302
            )
        except requests.RequestException as e:
            log_line(task, f"[-] 请求错误：{e}")
            continue

        code = resp.status_code
        content_type = (resp.headers.get("Content-Type") or "").lower()
        content_length = int(resp.headers.get("Content-Length") or 0)

        # 判断是否可能是备份文件
        if code in (200, 206) and looks_like_backup(resp.url):
            # 过滤明显是小的 HTML 页面（伪 200）
            if "text/html" in content_type and content_length < 2 * 1024 * 1024:
                log_line(task, f"[-] 看起来是HTML页面，跳过：{resp.url}")
                continue

            safe_name = resp.url.split("://", 1)[-1].replace("/", "_")
            save_dir = os.path.join(output_dir, host_tag)
            save_path = os.path.join(save_dir, safe_name)

            log_line(task, f"[!] 发现疑似备份文件：{resp.url}")
            log_line(task, f"    保存到：{save_path}")
            try:
                save_response_content(resp, save_path)
                found_count += 1
                update_target_status(task, target_index, found=found_count)
            except Exception as e:
                log_line(task, f"[-] 保存失败：{e}")
        else:
            log_line(task, f"[-] 无效（HTTP {code}）：{resp.url}")

    update_target_status(task, target_index, status="done")
    with TASKS_LOCK:
        task["finished_targets"] += 1
        done = task["finished_targets"]
        total = task["total_targets"]
    log_line(task, f"[*] 目标 {base_url} 扫描完成 ({done}/{total})")


def scan_worker(task_id: str):
    """后台线程入口：扫描整个任务所有目标"""
    with TASKS_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return

    targets = [t["name"] for t in task["targets"]]
    paths = task["paths"]

    max_workers = min(len(targets), task["max_workers"])
    if max_workers < 1:
        max_workers = 1

    log_line(task, f"[*] 启动扫描任务：{len(targets)} 个目标，字典 {len(paths)} 条，线程数 {max_workers}")
    log_line(task, f"[*] 备份文件将保存到：{DOWNLOAD_DIR}")

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for idx, target in enumerate(targets):
                futures.append(
                    executor.submit(scan_single_target, idx, target, DOWNLOAD_DIR, paths, task)
                )

            # 等待所有线程结束（捕获异常写到日志）
            for f in futures:
                try:
                    f.result()
                except Exception as e:
                    log_line(task, f"[!] 线程执行异常：{e}")
                    log_line(task, traceback.format_exc())
    finally:
        log_line(task, "\n[*] 所有目标扫描完成。")
        with TASKS_LOCK:
            task["done"] = True


@app.route("/", methods=["GET"])
def index():
    # 前端页面只负责展示和发起任务
    return render_template("index.html")


@app.route("/start", methods=["POST"])
def start_scan():
    try:
        # 1. 目标列表（文本框）
        targets_text = request.form.get("targets_text", "").strip()
        targets = []
        if targets_text:
            for line in targets_text.splitlines():
                line = line.strip()
                if line:
                    targets.append(line)

        # 2. 上传的目标 TXT 文件
        targets_file = request.files.get("targets_file")
        if targets_file and targets_file.filename:
            try:
                content = targets_file.read().decode("utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip()
                    if line:
                        targets.append(line)
            except Exception as e:
                return jsonify({"error": f"读取目标文件失败: {e}"}), 400

        # 去重
        targets = list(dict.fromkeys(targets))

        if not targets:
            return jsonify({"error": "没有有效的目标，请输入或上传目标列表"}), 400

        # 3. 字典路径
        paths = []

        # 3.1 文本框字典
        dict_text = request.form.get("dict_text", "").strip()
        if dict_text:
            for line in dict_text.splitlines():
                line = line.strip().lstrip("/\\")  # 去掉开头的 / 或 \
                if line:
                    paths.append(line)

        # 3.2 上传字典 TXT 文件
        dict_file = request.files.get("dict_file")
        if dict_file and dict_file.filename:
            try:
                content = dict_file.read().decode("utf-8", errors="ignore")
                for line in content.splitlines():
                    line = line.strip().lstrip("/\\")
                    if line:
                        paths.append(line)
            except Exception as e:
                return jsonify({"error": f"读取字典文件失败: {e}"}), 400

        # 都没给字典就用默认字典
        if not paths:
            paths = DEFAULT_PATHS.copy()

        # 4. 并发线程数
        try:
            threads_raw = request.form.get("threads", "5")
            max_workers = int((threads_raw or "5").strip())
        except Exception:
            max_workers = 5
        if max_workers <= 0:
            max_workers = 1
        if max_workers > 50:
            max_workers = 50

        # 5. 创建任务
        task_id = str(uuid.uuid4())
        with TASKS_LOCK:
            TASKS[task_id] = {
                "id": task_id,
                "logs": [],
                "targets": [
                    {"name": t, "status": "pending", "found": 0}
                    for t in targets
                ],
                "total_targets": len(targets),
                "finished_targets": 0,
                "paths": paths,
                "max_workers": max_workers,
                "done": False,
            }

        # 6. 启动后台线程执行扫描
        t = threading.Thread(target=scan_worker, args=(task_id,), daemon=True)
        t.start()

        return jsonify({"task_id": task_id})

    except Exception as e:
        # 捕获所有异常，返回 JSON，避免前端收到 HTML 错误页
        app.logger.exception("start_scan failed")
        return jsonify({
            "error": f"服务器内部错误: {e}",
            "detail": traceback.format_exc()
        }), 500


@app.route("/progress/<task_id>", methods=["GET"])
def progress(task_id):
    try:
        with TASKS_LOCK:
            task = TASKS.get(task_id)

            if not task:
                return jsonify({"error": "任务不存在"}), 404

            data = {
                "done": task["done"],
                "logs": task["logs"],
                "targets": task["targets"],
                "total_targets": task["total_targets"],
                "finished_targets": task["finished_targets"],
            }

        return jsonify(data)

    except Exception as e:
        app.logger.exception("progress failed")
        return jsonify({
            "error": f"服务器内部错误: {e}",
            "detail": traceback.format_exc()
        }), 500


if __name__ == "__main__":
    # 开发阶段 debug=True，方便看错误；自己用就无所谓
    app.run(host="127.0.0.1", port=5000, debug=True)