"""Clear infected encounters in the visible map without panning."""
import argparse
import json
import time
from PIL import ImageGrab
import app
import automation
import control
import settlement
from paths import COMBAT

def run_campaign(progress=lambda text:None,scope='visible',resume_current=False):
    scope='visible' # Legacy world callers also obey the no-map-drag setting.
    report={'status':'running','scope':scope,'battles':[],'scanned_views':0}
    output=COMBAT/'campaign-result.json'
    if resume_current and output.exists():
        report=json.loads(output.read_text(encoding='utf-8'))
        report['scope']='visible'
        report['status']='running';report.pop('error',None)
    def save(): output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    control.check();hwnd=app.find_game()
    if app.user32.IsIconic(hwnd): app.user32.ShowWindow(hwnd,9)
    app.focus_game(hwnd);box=app.bounds(hwnd)
    def capture():
        control.check()
        if app.user32.GetForegroundWindow()!=hwnd or app.bounds(hwnd)!=box:
            raise RuntimeError('窗口或焦点改变，连续清理已停止。')
        return ImageGrab.grab(bbox=box,all_screens=True)
    try:
        if resume_current:
            number=len(report['battles'])+1
            result=automation.run_battle(progress=lambda text:progress(f'第 {number} 场：{text}'),resume=True)
            report['battles'].append({'number':number,'attacks':len(result['actions']),
                                     'target':result['encounter']['target'],'returned_to_map':True})
            save()
        empty_scans=0
        while True:
            control.check()
            progress(f"已完成 {len(report['battles'])} 场，正在检查地图 Attack 入口…")
            scan=app.encounter(False,allow_empty=True,first_only=True,entry_only=True)
            report['scanned_views']+=1;save()
            if scan['candidates']:
                empty_scans=0
                number=len(report['battles'])+1
                result=automation.run_battle(
                    progress=lambda text:progress(f'第 {number} 场：{text}'),encounter_scan=scan)
                report['battles'].append({'number':number,'attacks':len(result['actions']),
                                           'target':scan['target'],'returned_to_map':True})
                save()
                continue
            empty_scans+=1
            if empty_scans<3:
                progress('本次未发现入口，等待地图刷新后再次扫描…')
                time.sleep(.2)
                continue
            break
        report.pop('no_infected_confirmed',None)
        report['status']='complete';report['no_attack_entry_confirmed']=True;save()
        progress(f"清理完成，共 {len(report['battles'])} 场，当前画面没有可识别的 Attack 入口。")
        return report
    except Exception as exc:
        report['status']='stopped';report['error']=str(exc);save();raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scope',choices=('world','visible'),default='visible')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();control.reset()
    print(json.dumps(run_campaign(lambda text:print(text,flush=True),args.scope,args.resume),ensure_ascii=True))
