import random
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait as fut_wait
from datetime import datetime
from typing import Any, Callable, Optional

import reg_gpt.console as console
from reg_gpt.runtime_state import update_summary, update_worker_slot


def print_attempt_header(n: int) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n{console.separator('─', 48)}")
    print(f"  {console.cyan(f'第 {n} 次')}  {console.gray(ts)}")
    print(console.separator('─', 48))


def run_sequential(
    *,
    proxy: Optional[str],
    sleep_min: int,
    sleep_max: int,
    max_success: int,
    once: bool,
    run_func: Callable[[Optional[str]], tuple[Optional[str], str, str]],
    save_func: Callable[[str, str, str], str],
) -> None:
    count = 0
    success_count = 0

    while True:
        count += 1
        update_summary(attempts=count, failures=count - success_count, phase="running", workers_active=1)
        update_worker_slot(1, status="running", attempt=count, email="")
        print_attempt_header(count)

        try:
            token_json, reg_email, reg_password = run_func(proxy)
            if token_json:
                fname = save_func(token_json, reg_email, reg_password)
                console.print_ok(f"Token 已保存  {console.dim(fname)}")
                success_count += 1
                update_worker_slot(1, status="success", attempt=count, email=reg_email)
                update_summary(
                    successes=success_count,
                    failures=count - success_count,
                    last_email=reg_email,
                    message="主程序运行中",
                )
                if max_success > 0:
                    pct = success_count / max_success * 100
                    console.print_info(f"进度  {console.green(str(success_count))}/{max_success}  ({pct:.1f}%)")
                else:
                    console.print_info(f"累计成功  {console.green(str(success_count))}")
            else:
                console.print_fail("本次注册失败")
                update_worker_slot(1, status="failed", attempt=count, email=reg_email)
                update_summary(failures=count - success_count, message="主程序运行中")
        except Exception as exc:
            console.print_err(f"未捕获异常: {exc}")
            update_worker_slot(1, status="failed", attempt=count)
            update_summary(failures=count - success_count, message="主程序运行中")

        if max_success > 0 and success_count >= max_success:
            print(f"\n{console.green('✓')} 已达到目标数量 {max_success}，停止运行")
            update_summary(
                workers_active=0,
                phase="completed",
                message=f"已达到目标数量 {max_success}",
                successes=success_count,
                failures=count - success_count,
            )
            break

        if once:
            update_summary(
                workers_active=0,
                phase="completed",
                message="单次运行已完成",
                successes=success_count,
                failures=count - success_count,
            )
            break

        wait_time = random.randint(sleep_min, sleep_max)
        update_worker_slot(1, status="sleeping", attempt=count)
        update_summary(workers_active=1, message=f"等待 {wait_time}s 后继续")
        console.print_info(f"等待 {wait_time}s ...")
        time.sleep(wait_time)


def run_parallel(
    *,
    proxy: Optional[str],
    workers: int,
    sleep_min: int,
    sleep_max: int,
    max_success: int,
    once: bool,
    run_func: Callable[[Optional[str], str, int], tuple[Optional[str], str, str]],
    save_func: Callable[[str, str, str], str],
    on_parallel_start: Callable[[Optional[str], int], Any],
    on_parallel_stop: Callable[[Any], None],
) -> None:
    runtime_ctx = on_parallel_start(proxy, workers)
    logger = runtime_ctx["logger"]
    lock = threading.Lock()
    state = {"attempts": 0, "successes": 0, "stop": False}
    update_summary(workers_active=workers, phase="running", message="并行 Worker 已启动")

    def task(wid: int, is_first: bool = False):
        if not is_first:
            with lock:
                if state["stop"]:
                    return None
            wait_t = random.randint(sleep_min, sleep_max)
            update_worker_slot(wid, status="sleeping")
            console.wlog(wid, f"  {console.dim(f'W{wid}')}  {console.dim(f'等待 {wait_t}s...')}")
            time.sleep(wait_t)

        with lock:
            if state["stop"]:
                return None
            state["attempts"] += 1
            n = state["attempts"]
            update_summary(attempts=n, failures=n - state["successes"])

        tag = f"W{wid} "
        update_worker_slot(wid, status="running", attempt=n, email="")
        console.wlog(wid, f"{console.cyan(f'── W{wid} 开始第 {n} 次注册')}  {console.gray(datetime.now().strftime('%H:%M:%S'))}")
        try:
            token_json, reg_email, reg_password = run_func(proxy, tag, wid)
        except Exception as exc:
            console.wlog(wid, f"  {console.red(f'[W{wid}]')}  未捕获异常: {exc}")
            token_json, reg_email, reg_password = None, "", ""
        return token_json, reg_email, reg_password, n, wid

    logger.notice(f"{console.cyan('[·]')} 并行 Worker: {console.cyan(str(workers))}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(task, slot, True) for slot in range(1, workers + 1)}

        while pending:
            done, pending = fut_wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                try:
                    result = fut.result()
                except Exception as exc:
                    logger.event(f"  {console.red('✗')}  Worker 异常: {exc}")
                    result = None

                if result is None:
                    continue

                token_json, reg_email, reg_password, n, wid = result
                if token_json:
                    save_func(token_json, reg_email, reg_password)
                    with lock:
                        state["successes"] += 1
                        sc = state["successes"]
                    update_worker_slot(wid, status="success", attempt=n, email=reg_email)
                    update_summary(
                        successes=sc,
                        failures=state["attempts"] - sc,
                        last_email=reg_email,
                    )
                    if max_success > 0:
                        pct = sc / max_success * 100
                        logger.event(
                            f"  {console.green('✓')}  W{wid}  #{n}  "
                            f"{console.green(reg_email)}  "
                            f"进度 {console.green(str(sc))}/{max_success} ({pct:.1f}%)"
                        )
                        if sc >= max_success:
                            with lock:
                                state["stop"] = True
                            update_summary(
                                phase="completed",
                                workers_active=0,
                                message=f"已达到目标数量 {max_success}",
                            )
                            logger.event(f"{console.green('✓')} 已达到目标数量 {max_success}，停止所有 Worker")
                    else:
                        logger.event(
                            f"  {console.green('✓')}  W{wid}  #{n}  "
                            f"{console.green(reg_email)}  累计成功 {console.green(str(sc))}"
                        )
                else:
                    update_worker_slot(wid, status="failed", attempt=n, email=reg_email)
                    update_summary(failures=state["attempts"] - state["successes"])
                    logger.event(
                        f"  {console.red('✗')}  W{wid}  #{n}  "
                        f"{console.dim(reg_email or '—')}  注册失败"
                    )

                with lock:
                    should_stop = state["stop"]
                if not once and not should_stop:
                    pending.add(pool.submit(task, wid, False))

    on_parallel_stop(runtime_ctx)

    with lock:
        sc = state["successes"]
        at = state["attempts"]
    for wid in range(1, workers + 1):
        update_worker_slot(wid, status="stopped")
    update_summary(
        attempts=at,
        successes=sc,
        failures=at - sc,
        workers_active=0,
        phase="completed",
        message="并行任务已结束",
    )
    print(f"\n{console.separator()}")
    print(f"  总尝试 {at}   成功 {console.green(str(sc))}   失败 {console.red(str(at - sc))}")
    print(console.separator())
