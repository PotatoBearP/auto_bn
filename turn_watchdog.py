"""Record stalled turns without changing battle decisions or sending input."""
from collections import deque
from contextvars import ContextVar
from datetime import datetime
import json
import shutil
import time

CURRENT=ContextVar('turn_watchdog',default=None)
TURN_TIMEOUT_SECONDS=60


def event(stage,details=None):
    monitor=CURRENT.get()
    if monitor is not None: monitor.event(stage,details)


def observe(image):
    monitor=CURRENT.get()
    if monitor is not None: monitor.observe(image)


class TurnWatchdog:
    def __init__(self,root,notify=lambda text:None,environment=lambda:{},clock=None):
        self.root=root
        self.notify=notify
        self.environment=environment
        self.clock=clock or time.monotonic
        self.last_progress=self.clock()
        self.last_progress_at=datetime.now().isoformat(timespec='seconds')
        self.turn=1
        self.recorded=False
        self.stage='battle_started'
        self.details={}
        self.history=deque(maxlen=100)
        self.incidents=[]

    def event(self,stage,details=None):
        self.stage=stage
        if details: self.details.update(details)
        self.history.append({'elapsed_seconds':round(self.clock()-self.last_progress,3),
                             'stage':stage})

    def progressed(self):
        self.last_progress=self.clock()
        self.last_progress_at=datetime.now().isoformat(timespec='seconds')
        self.turn+=1
        self.recorded=False
        self.details={}
        self.history.clear()
        self.event('confirmed_next_turn')

    def observe(self,image):
        elapsed=self.clock()-self.last_progress
        if elapsed<=TURN_TIMEOUT_SECONDS or self.recorded: return
        self.recorded=True
        directory=self.root/'anomalies'/datetime.now().strftime('turn-stall-%Y%m%d-%H%M%S-%f')
        try:
            directory.mkdir(parents=True)
            errors=[]
            try: image.save(directory/'current-screen.png')
            except Exception as exc: errors.append(f'screenshot: {exc}')
            try: environment=self.environment()
            except Exception as exc: environment={'error':str(exc)}
            copied=[]
            # Copy raw evidence; observing again here could change model history.
            for name in ('active-formation.json','ally-state.json','battle-state.json',
                         'enemy-board.json','enemy-board.txt','combat-result.json',
                         'automation-result.json','sweep-result.json','reticle-detection.json',
                         'combat-before.png','combat-chosen-preview.png','combat-after.png'):
                source=self.root/name
                if not source.exists(): continue
                try:
                    shutil.copy2(source,directory/name);copied.append(name)
                except OSError as exc: errors.append(f'{name}: {exc}')
            snapshot={'reason':'turn_timeout','threshold_seconds':TURN_TIMEOUT_SECONDS,
                      'elapsed_without_turn_progress_seconds':round(elapsed,3),
                      'observed_turn':self.turn,'last_confirmed_turn_at':self.last_progress_at,
                      'recorded_at':datetime.now().isoformat(timespec='seconds'),
                      'stage':self.stage,'current_observation':self.details,
                      'recent_events':list(self.history),'environment':environment,
                      'copied_files':copied,'capture_errors':errors,
                      'behavior':'record_once_per_stalled_turn_and_continue_retrying',
                      'note':'Copied runtime files retain their timestamps and may describe a prior action.'}
            (directory/'snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
            self.incidents.append(str(directory))
            self.notify(f'异常：超过 60 秒未确认回合推进，已保存现场：{directory}。继续识别并重试。')
        except OSError as exc:
            self.notify(f'异常：超过 60 秒未确认回合推进，现场保存失败：{exc}。继续重试。')
