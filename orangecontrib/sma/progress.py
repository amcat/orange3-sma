from Orange.widgets.widget import OWWidget
from progressmonitor import ProgressMonitor


def progress_monitor(widget: OWWidget, status_attr=None, start_msg='Started', done_msg='Done') -> ProgressMonitor:
    def status(msg):
        if status_attr and hasattr(widget, status_attr):
            setattr(widget, status_attr, msg)

    def on_progress_update(m: ProgressMonitor):
        if m.is_done:
            widget.progressBarFinished()
            if done_msg:
                status(done_msg)
        else:
            widget.progressBarSet(m.progress * 100)
            status(m.message)

    widget.progressBarInit()
    if start_msg:
        status(start_msg)
    m = ProgressMonitor()
    m.add_listener(on_progress_update)
    return m
