"""Three front-row cowards; finish wounded targets, confirm defeat and repeat."""
import target_priority
import sweep
from attrition_opening import prepare

CONFIG={'version':1,'units':[{'row':1,'column':c,'unit':'coward'} for c in (1,3,5)]}

def run_loop(progress=lambda text:None,max_battles=None):
    token=target_priority.ATTRITION.set(True)
    try:
        return sweep.run_loop(progress=progress,max_battles=max_battles,config=CONFIG,
                              report_name='attrition-result.json',opening_gate=prepare)
    finally:
        target_priority.ATTRITION.reset(token)

if __name__=='__main__':
    import argparse
    import control
    parser=argparse.ArgumentParser()
    parser.add_argument('--battles',type=int)
    args=parser.parse_args()
    control.reset()
    run_loop(progress=print,max_battles=args.battles)
