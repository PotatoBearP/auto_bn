"""Repeat the current encounter, deploying only for the first battle."""
import json
from PIL import ImageGrab
import app
import automation
import combat
import control
import deployment
import formation
import settlement
from paths import COMBAT


def run_loop(progress=lambda text:None,max_battles=None,config=None):
    if max_battles is not None and max_battles<1: raise ValueError('扫荡场数至少为 1。')
    config=formation.validate(config if config is not None else formation.load_sweep())
    report={'status':'running','formation':config,'battles':[]}
    path=COMBAT/'sweep-result.json'
    def save(): path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        control.check()
        hwnd=app.find_game()
        if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
        app.focus_game(hwnd);box=app.bounds(hwnd)
        def capture():
            control.check()
            if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
                raise RuntimeError('窗口或焦点改变，自动扫荡已停止。')
            return ImageGrab.grab(bbox=box,all_screens=True)
        frame=capture()
        if deployment.start_button_visible(frame):
            deployment.locate_start_button(frame)
            progress('自动扫荡：首场按扫荡阵容布阵并开战…')
            report['deployment']=deployment.deploy_formation(config);save()
            report['start']=deployment.start_battle(config);save()
        else:
            phase=settlement.phase(frame)
            if (phase=='map' or formation.active()!=config or
                not (phase in ('loot','experience') or combat.skill_panel_visible(frame))):
                raise RuntimeError('请打开扫荡布阵界面；接续战斗时扫荡设置须与当前已部署阵容一致。')
            report['resumed_current']=True;save()
            progress('接续当前扫荡战斗，沿用已部署阵容。')
        while max_battles is None or len(report['battles'])<max_battles:
            capture()
            number=len(report['battles'])+1
            progress(f'自动扫荡：第 {number} 场，按 Esc 停止。')
            result=automation.run_battle(progress=lambda text:progress(f'扫荡第 {number} 场：{text}'),
                                         start_current=True,settlement_mode='repeat')
            next_start=None
            if result['settlement'].get('next_deployment_ready'):
                capture()
                progress('阵容已沿用，直接点击开战；不添加或移动单位。')
                next_start=deployment.start_battle(config,verify_placement=False)
            elif result['settlement'].get('next_battle_ready'):
                combat.reset_battle_state();formation.activate(config)
            else:
                raise RuntimeError('未确认下一场扫荡就绪。')
            report['battles'].append({'number':number,'actions':result['actions'],
                                      'settlement':result['settlement'],'next_start':next_start});save()
        report['status']='complete';save()
        return report
    except Exception as exc:
        report['status']='stopped';report['error']=str(exc);save();raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--battles',type=int)
    args=parser.parse_args();control.reset()
    run_loop(progress=lambda text:print(text,flush=True),max_battles=args.battles)
