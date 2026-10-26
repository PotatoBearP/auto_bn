"""Run exactly one infected encounter from world map to settlement."""
import json
import time
from PIL import ImageGrab
import app
import combat
import control
import deployment
import settlement
import turn_watchdog
from paths import COMBAT

def run_battle(progress=lambda message:None,max_actions=100,timeout=900,resume=False,encounter_scan=None,
               start_current=False,settlement_mode='map'):
    if settlement_mode not in ('map','repeat'): raise ValueError('未知结算模式。')
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
    monitor=None;monitor_token=None
    try:
        if resume and deployment.start_button_visible(capture()):
            progress('接续尚未开战的布阵界面，核验阵型后开战…')
            report['deployment']=deployment.deploy_and_start();save()
        if not resume and not start_current:
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
        monitor=turn_watchdog.TurnWatchdog(COMBAT,notify=progress,environment=lambda:{
            'game_window':hwnd,'expected_bounds':box,'current_bounds':app.bounds(hwnd),
            'foreground_window':app.user32.GetForegroundWindow()})
        monitor_token=turn_watchdog.CURRENT.set(monitor)
        report['anomalies']=monitor.incidents
        completed=sum(bool(action.get('confirmed')) for action in report['actions'])
        while completed<max_actions:
            number=len(report['actions'])+1
            frame=capture()
            if settlement.phase(frame) in ('loot','experience'): break
            monitor.event('before_action',{'action_number':number})
            monitor.observe(frame)
            if time.monotonic()>=deadline: raise RuntimeError('战斗超时，已停止自动化。')
            progress(f'正在执行第 {number} 次攻击：分析技能覆盖与冷却…')
            try:
                step=combat.combat_step()
            except combat.CombatRetry as exc:
                progress(f'战斗状态暂未就绪：{exc} 等待后重新识别并尝试释放。')
                monitor.event('retry',{'retry_reason':str(exc)})
                monitor.observe(capture());save()
                time.sleep(.3)
                continue
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
            if step.get('release_confirmed') or step.get('skip_confirmed'):
                completed+=1
                # A cooldown alone confirms a release, not the next turn.
                if step.get('settled'): monitor.progressed()
            monitor.event('action_result',{'last_step':step})
            monitor.observe(capture());save()
            if step.get('skipped') and step.get('skip_confirmed') and step.get('settled'):
                progress('已跳过回合，等待并重新分析技能后继续攻击。')
                continue
            if not step.get('released') or not step.get('release_confirmed'):
                progress('本次释放尚未确认，等待后重新识别技能并重试。')
                capture();time.sleep(.3)
                continue
            if not step.get('settled'):
                progress('下一回合尚未稳定，继续等待并重新识别。')
                capture();time.sleep(.3)
                continue
        else:
            raise RuntimeError('达到本场攻击次数上限，已停止。')
        progress('战斗结束，正在确认战利品和经验…')
        report['settlement']=(settlement.finish_battle(next_battle=True) if settlement_mode=='repeat'
                              else settlement.finish_battle())
        report['status']='complete';save()
        progress('本场完成，下一场入口已就绪。' if settlement_mode=='repeat' else
                 '本场全自动战斗完成，已返回大地图。')
        return report
    except Exception as exc:
        report['status']='stopped';report['error']=str(exc);save()
        raise
    finally:
        if monitor_token is not None: turn_watchdog.CURRENT.reset(monitor_token)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    control.reset()
    result=run_battle(progress=lambda message:print(message,flush=True),resume=args.resume)
    print(json.dumps({'status':result['status'],'attacks':len(result['actions'])},ensure_ascii=True))
