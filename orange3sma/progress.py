from Orange.widgets.widget import OWWidget
from progressmonitor import ProgressMonitor


def progress_monitor(widget: OWWidget, status_attr=None, start_msg='Started', done_msg='Done') -> ProgressMonitor:
    def on_progress_update(m: ProgressMonitor):
        if m.is_done:
            widget.progressBarFinished()
            if hasattr(widget, status_attr):
                setattr(widget, status_attr, done_msg)
        else:
            widget.progressBarSet(m.progress * 100)
            if hasattr(widget, status_attr):
                setattr(widget, status_attr, m.message)


    widget.progressBarInit()
    if hasattr(widget, status_attr):
        setattr(widget, status_attr, start_msg)
    m = ProgressMonitor()
    m.add_listener(on_progress_update)
    return m
