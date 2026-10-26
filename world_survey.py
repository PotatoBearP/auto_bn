"""Visit world-map camera bounds with overlapping serpentine sweeps."""
import time
import numpy as np
from PIL import ImageStat
import mouse_backend as mouse
import settlement
import control
from paths import ENCOUNTER


def motion_score(before,after):
    region=(110,90,min(1250,before.width),min(670,before.height))
    a=np.asarray(before.crop(region).resize((160,80)).convert('RGB'),dtype=np.int16)
    b=np.asarray(after.crop(region).resize((160,80)).convert('RGB'),dtype=np.int16)
    return float(np.mean(np.minimum(np.abs(a-b),60)))


def drag_source(image,dx,dy):
    candidates=[]
    rgb=image.convert('RGB')
    for y in range(120,650,35):
        for x in range(120,1250,35):
            if not (110<=x+dx<=1250 and 100<=y+dy<=665): continue
            crop=rgb.crop((x-12,y-12,x+12,y+12))
            stats=ImageStat.Stat(crop);r,g,b=stats.mean
            water=b>90 and b>r*1.25 and g>r*1.2
            terrain=r>95 and g>65 and b<175 and r>g*.8 and not (r>g*1.22 and g>b*1.4)
            if not (water or terrain): continue
            variance=sum(stats.var)/3
            if variance<450: candidates.append((not water,variance,x,y))
    if not candidates: raise RuntimeError('未找到安全的地图空白拖动位置。')
    _,_,x,y=min(candidates)
    return x,y


class WorldSurvey:
    def __init__(self,box,capture,progress=lambda text:None):
        self.box=box;self.capture=capture;self.progress=progress
        self.started=False;self.direction=-1;self.views=0;self.audit=[]

    def pan(self,dx,dy):
        before=self.capture()
        if not settlement.map_visible(before): raise RuntimeError('当前不是世界地图，取消拖动。')
        x,y=drag_source(before,dx,dy)
        def check():
            control.check();self.capture()
        mouse.drag((self.box[0]+x,self.box[1]+y),
                   (self.box[0]+x+dx,self.box[1]+y+dy),check)
        time.sleep(.4);after=self.capture()
        score=motion_score(before,after)
        moved=score>2.5
        self.audit.append({'delta':[dx,dy],'source':[x,y],'motion_score':round(score,3),'moved':moved})
        after.save(ENCOUNTER/'world-survey-current.png')
        return moved

    def next_view(self):
        if self.views>=100: raise RuntimeError('地图巡查超过 100 个视野，未宣称全图完成。')
        if not self.started:
            self.progress('当前视野已清理，定位地图西北边界，开始全图巡查。')
            for delta in ((600,0),(0,350)):
                for attempt in range(12):
                    if not self.pan(*delta): break
                else: raise RuntimeError('未确认地图边界，停止全图完成判定。')
            self.started=True;self.views+=1
            return True
        self.progress(f'全图巡查：切换第 {self.views+1} 个重叠视野。')
        if self.pan(self.direction*600,0):
            self.views+=1;return True
        if self.pan(0,-350):
            self.direction*=-1;self.views+=1;return True
        return False
