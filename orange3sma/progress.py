from Orange.widgets.widget import OWWidget
from progressmonitor import ProgressMonitor


def progress_monitor(widget: OWWidget) -> ProgressMonitor:
    def on_progress_update(m: ProgressMonitor):
        if m.is_done:
            widget.progressBarFinished()
        else:
            widget.progressBarSet(m.progress * 100)

    widget.progressBarInit()
    m = ProgressMonitor()
    m.add_listener(on_progress_update)
    return m
