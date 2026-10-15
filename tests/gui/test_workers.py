from dataclasses import replace

import numpy as np

from plotter.config import Config
from plotter.grbl_sender import GrblError
from plotter.gui.workers import ProcessThread, SendThread


def run_thread(qapp, thread):
    thread.start()
    assert thread.wait(5000)
    qapp.processEvents()


class FakeSender:
    def __init__(self, result=True, error=None):
        self.result, self.error = result, error

    def stream(self, commands, on_progress):
        for i in range(1, len(commands) + 1):
            on_progress(i, len(commands))
        if self.error:
            raise self.error
        return self.result


def test_process_thread_reports_processing_error(qapp):
    cfg = replace(Config(), potrace_path="C:/nope/potrace.exe")
    thread = ProcessThread(np.full((20, 20), 255, np.uint8), cfg)
    failures, results = [], []
    thread.failed.connect(failures.append)
    thread.succeeded.connect(results.append)
    run_thread(qapp, thread)
    assert results == []
    assert len(failures) == 1 and "potrace" in failures[0]


def test_send_thread_reports_progress_and_completion(qapp):
    thread = SendThread(FakeSender(result=True), ["G21", "G90"])
    progress, done = [], []
    thread.progress.connect(lambda d, t: progress.append((d, t)))
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert progress == [(1, 2), (2, 2)]
    assert done == [True]


def test_send_thread_reports_stop(qapp):
    thread = SendThread(FakeSender(result=False), ["G21"])
    done = []
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert done == [False]


def test_send_thread_reports_grbl_error(qapp):
    thread = SendThread(FakeSender(error=GrblError("1번째 줄 'G21'에서 GRBL 오류: error:20")), ["G21"])
    failures, done = [], []
    thread.failed.connect(failures.append)
    thread.completed.connect(done.append)
    run_thread(qapp, thread)
    assert failures == ["1번째 줄 'G21'에서 GRBL 오류: error:20"]
    assert done == []


def test_send_thread_wraps_unexpected_error(qapp):
    thread = SendThread(FakeSender(error=RuntimeError("boom")), ["G21"])
    failures = []
    thread.failed.connect(failures.append)
    run_thread(qapp, thread)
    assert failures and "boom" in failures[0]
