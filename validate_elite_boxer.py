"""Run fresh infected encounters through the normal automation for live QA."""
import json
from PIL import ImageGrab
import app
import automation
import control
import formation
import settlement
from paths import COMBAT


def run(progress=print,battles=3,resume=False):
    if battles<1: raise ValueError('验收场数必须大于零。')
    config=formation.load()
    if not config['units'] or any(u['unit']!='elite_boxer' for u in config['units']):
        raise ValueError('请先将感染者阵型保存为顶尖拳击手阵容。')
    directory=COMBAT/'elite-boxer-acceptance'
    directory.mkdir(parents=True,exist_ok=True)
    path=directory/'result.json'
    report={'status':'running','formation':config,'required_battles':battles,'battles':[]}
    if resume and path.exists():
        report=json.loads(path.read_text(encoding='utf-8'))
        if report['formation']!=config: raise ValueError('接续验收时阵容不可改变。')
        report['status']='running';report.pop('error',None)
    def save(): path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    try:
        first=len(report['battles'])+1
        for number in range(first,battles+1):
            progress(f'顶尖拳击手验收 {number}/{battles}：从地图自动识别感染者并布阵。')
            hwnd=app.find_game();app.focus_game(hwnd)
            before=ImageGrab.grab(bbox=app.bounds(hwnd),all_screens=True)
            before_path=directory/f'battle-{number}-map-before.png'
            if not before_path.exists() or not resume: before.save(before_path)
            result=automation.run_battle(progress=lambda s:progress(f'验收第 {number} 场：{s}'),
                resume=bool(resume and number==first and settlement.phase(before)!='map'))
            if result.get('status')!='complete' or result['encounter']['target'].get('enemy')!='感染者':
                raise RuntimeError('未确认感染者战斗完整结算。')
            deployed=result.get('deployment',{}).get('formation')
            if deployed!=config: raise RuntimeError('实际布阵与验收阵容不一致。')
            if not any(a.get('skill')==3 and a.get('confirmed') for a in result['actions']):
                raise RuntimeError('本场未记录到已确认的第三技能释放。')
            ImageGrab.grab(bbox=app.bounds(hwnd),all_screens=True).save(directory/f'battle-{number}-map-after.png')
            (directory/f'battle-{number}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            report['battles'].append({'number':number,'status':'complete',
                'target':result['encounter']['target'],'actions':result['actions'],
                'settlement':result['settlement'],'evidence':f'battle-{number}.json'})
            save()
        report['status']='complete';save()
        return report
    except Exception as exc:
        report.update(status='stopped',error=str(exc));save();raise


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    control.reset()
    run(progress=lambda text:print(text,flush=True),resume=args.resume)
