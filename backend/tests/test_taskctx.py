"""任务上下文（taskctx）单元测试：含 M8b 线程修复的回归覆盖。"""
import threading

from nvwa_agent.core import taskctx


def test_default_is_system():
    assert taskctx.get_current_task() == "system"


def test_set_and_clear():
    taskctx.set_current_task("t-1")
    assert taskctx.get_current_task() == "t-1"
    taskctx.clear_current_task()
    assert taskctx.get_current_task() == "system"


def test_new_thread_does_not_inherit():
    """新线程不继承父线程 ContextVar —— 修复 queue.py 的原因，此为回归基线。"""
    taskctx.set_current_task("t-parent")
    try:
        result = {}
        def child():
            result["value"] = taskctx.get_current_task()
        t = threading.Thread(target=child)
        t.start()
        t.join()
        assert result["value"] == "system"
    finally:
        taskctx.clear_current_task()


def test_set_inside_thread_visible_in_same_thread():
    """线程内自行 set 后，同线程内（含 LangGraph 节点调用链）可正确读取。"""
    result = {}
    def child():
        taskctx.set_current_task("t-worker")
        # 模拟嵌套函数调用（如 graph.invoke -> llm.chat -> event_bus.publish）
        def nested():
            return taskctx.get_current_task()
        result["nested"] = nested()
    t = threading.Thread(target=child)
    t.start()
    t.join()
    assert result["nested"] == "t-worker"
