"""Backend-owned sector archival; preserve the application's existing lifespan."""
import threading
from contextlib import asynccontextmanager

class SectorRecorder:
    def __init__(self):self.stop_event=threading.Event();self.thread=None;self.error=None
    def start(self):
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self.run,daemon=True,name='sector-session-archive');self.thread.start()
    def stop(self):self.stop_event.set()
    def run(self):
        from .sector_oi import sector_oi
        while not self.stop_event.is_set():
            try:sector_oi();self.error=None
            except Exception:self.error='Sector archive update failed; check data directory and collector status.'
            self.stop_event.wait(15)
    def status(self):return dict(running=bool(self.thread and self.thread.is_alive()),error=self.error)
recorder=SectorRecorder()

def install_sector_recording(app):
    if getattr(app.state,'sector_recording_installed',False):return
    previous=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(application):
        async with previous(application):
            recorder.start()
            try:yield
            finally:recorder.stop()
    app.router.lifespan_context=lifespan
    app.state.sector_recording_installed=True
