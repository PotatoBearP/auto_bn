"""Run exactly one infected encounter from world map to settlement."""
import json
import time
from PIL import ImageGrab
import app
import combat
import control
import deployment
import settlement
from paths import COMBAT

def run_battle(progress=lambda message:None,max_actions=100,timeout=900,resume=False,encounter_scan=None):
    report={'status':'running','actions':[]}
    path=COMBAT/'automation-result.json'
    if resume and path.exists():
        report=json.loads(path.read_text(encoding='utf-8'))
        report['status']='running';report.pop('error',None)
    def save():
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    control.check()
    hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd)
    box=app.bounds(hwnd)
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，全自动流程已停止。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    def wait_deployment():
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            image=capture()
            region=image.convert('RGB').crop((1200,450,1360,570))
            green=sum(g>100 and g>r*1.4 and g>b*1.4 for r,g,b in region.getdata())
            if green>=1500: return
            time.sleep(.1)
        raise RuntimeError('等待布阵界面超时，未重复点击 Attack。')
    try:
        if not resume:
            if settlement.phase(capture())!='map':
                raise RuntimeError('请从世界地图启动全自动流程。')
            progress('正在识别感染者并进入遭遇战…')
            if encounter_scan:
                report['encounter']=app.encounter(True,target=encounter_scan['target'])
            else:
                report['encounter']=app.encounter(True)
            save()
            wait_deployment()
            progress('正在按已保存的自定义阵型部署单位并开战…')
            report['deployment']=deployment.deploy_and_start();save()
        deadline=time.monotonic()+timeout
        for number in range(len(report['actions'])+1,max_actions+1):
            frame=capture()
            if settlement.phase(frame) in ('loot','experience'): break
            if time.monotonic()>=deadline: raise RuntimeError('战斗超时，已停止自动化。')
            progress(f'正在执行第 {number} 次攻击：分析技能覆盖与冷却…')
            step=combat.combat_step()
            if step.get('skipped'):
                report['actions'].append({'number':number,'action':'skip_turn',
                                         'confirmed':step.get('skip_confirmed',False)})
                save()
            if step.get('released'):
                choice=step['chosen']
                report['actions'].append({'number':number,'skill':choice['skill'],
                    'unit':choice['unit'],'target':choice['target'],
                    'hit_count':choice['hit_count'],'confirmed':step.get('release_confirmed',False)})
                save()
            if step.get('battle_ended'): break
            if step.get('skipped') and step.get('skip_confirmed') and step.get('settled'):
                progress('已跳过回合，等待并重新分析技能后继续攻击。')
                continue
            if not step.get('released') or not step.get('release_confirmed'):
                raise RuntimeError('本次释放未确认成功，停止追加攻击。')
            if not step.get('settled'):
                raise RuntimeError('未确认下一回合稳定，停止追加攻击。')
        else:
            raise RuntimeError('达到本场攻击次数上限，已停止。')
        progress('战斗结束，正在确认战利品和经验…')
        report['settlement']=settlement.finish_battle()
        report['status']='complete';save()
        progress('本场全自动战斗完成，已返回大地图。')
        return report
    except Exception as exc:
        report['status']='stopped';report['error']=str(exc);save()
        raise

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    control.reset()
    result=run_battle(progress=lambda message:print(message,flush=True),resume=args.resume)
    print(json.dumps({'status':result['status'],'attacks':len(result['actions'])},ensure_ascii=True))
