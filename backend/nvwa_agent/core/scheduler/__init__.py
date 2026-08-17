"""核心调度器：FIFO任务队列 + 意图识别 + Agent执行（§10）。"""
from nvwa_agent.core.scheduler.queue import enqueue, start_worker

__all__ = ["enqueue", "start_worker"]
