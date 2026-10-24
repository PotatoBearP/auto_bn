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
from target_priority import ATTRITION
from paths import COMBAT


def run_loop(progress=lambda text:None,max_battles=None,config=None,report_name='sweep-result.json',opening_gate=None):
    if max_battles is not None and max_battles<1: raise ValueError('扫荡场数至少为 1。')
    config=formation.validate(config if config is not None else formation.load_sweep())
    label='消耗战' if ATTRITION.get() else '扫荡'
    report={'status':'running','formation':config,'battles':[]}
    path=COMBAT/report_name
    def save(): path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        control.check()
        hwnd=app.find_game()
        if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
        app.focus_game(hwnd);box=app.bounds(hwnd)
        def capture():
            control.check()
            if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
                raise RuntimeError(f'窗口或焦点改变，自动{label}已停止。')
            return ImageGrab.grab(bbox=box,all_screens=True)
        frame=capture()
        if deployment.start_button_visible(frame):
            deployment.locate_start_button(frame)
            progress(f'自动{label}：首场按配置阵容布阵并开战…')
            report['deployment']=deployment.deploy_formation(config);save()
            report['start']=deployment.start_battle(config);save()
            if opening_gate:
                report['opening_checks']=[opening_gate(frame,progress=progress)];save()
        else:
            phase=settlement.phase(frame)
            if (phase=='map' or formation.active()!=config or
                not (phase in ('loot','experience') or combat.skill_panel_visible(frame))):
                raise RuntimeError(f'请打开{label}布阵界面；接续战斗时配置须与当前已部署阵容一致。')
            report['resumed_current']=True;save()
            progress(f'接续当前{label}战斗，沿用已部署阵容。')
            if opening_gate and phase is None:
                report['opening_checks']=[opening_gate(frame,progress=progress)];save()
        while max_battles is None or len(report['battles'])<max_battles:
            capture()
            number=len(report['battles'])+1
            total=f' / {max_battles}' if max_battles is not None else ''
            progress(f'自动{label}：第 {number}{total} 场，按 Esc 停止。')
            result=automation.run_battle(progress=lambda text:progress(f'{label}第 {number} 场：{text}'),
                                         start_current=True,settlement_mode='repeat')
            next_start=None
            if result['settlement'].get('next_deployment_ready'):
                opening_frame=capture()
                progress('阵容已沿用，直接点击开战；不添加或移动单位。')
                next_start=deployment.start_battle(config,verify_placement=False)
                if opening_gate:
                    report.setdefault('opening_checks',[]).append(opening_gate(opening_frame,progress=progress));save()
            elif result['settlement'].get('next_battle_ready'):
                combat.reset_battle_state();formation.activate(config)
                if opening_gate:
                    report.setdefault('opening_checks',[]).append(opening_gate(capture(),progress=progress));save()
            else:
                raise RuntimeError(f'未确认下一场{label}就绪。')
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
