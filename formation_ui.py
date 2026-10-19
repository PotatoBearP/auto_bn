"""Tk editor for the 13-cell formation; no game interaction."""
import tkinter as tk
from tkinter import ttk, messagebox
import formation
from unit_ai import choices

def open_editor(parent,on_saved=None,sweep=False):
    loader=formation.load_sweep if sweep else formation.load
    saver=formation.save_sweep if sweep else formation.save
    defaults=formation.sweep_defaults if sweep else formation.defaults
    window=tk.Toplevel(parent)
    window.title(('自动扫荡阵容' if sweep else '自定义布阵')+' · 5 / 5 / 3')
    window.geometry('820x520');window.resizable(False,False)
    window.transient(parent);window.grab_set()
    labels=choices();reverse={name:unit_id for unit_id,name in labels.items()}
    variables={}
    ttk.Label(window,text='自定义阵型（5 / 5 / 3）',font=('Microsoft YaHei UI',17,'bold')).pack(pady=(18,8))
    ttk.Label(window,text='前排靠近敌方；胆小鬼仅限第一排；第 3 排只有中间三格。').pack()
    board=ttk.Frame(window);board.pack(pady=18,padx=15)
    for row in range(1,4):
        for column in range(1,formation.ROWS[row-1]+1):
            frame=ttk.LabelFrame(board,text=f'第 {row} 排 · 第 {column} 格',padding=8)
            display_column=column if row<3 else column+1
            frame.grid(row=row-1,column=display_column-1,padx=5,pady=7)
            variable=tk.StringVar(window,value='空位');variables[row,column]=variable
            ttk.Combobox(frame,textvariable=variable,values=['空位',*labels.values()],
                         state='readonly',width=13).pack()
    ttk.Label(window,text='保存后用于自动扫荡首场布阵，后续由游戏沿用。' if sweep else
              '保存后用于感染者自动布阵和战斗。PVP 继续使用其专用送分阵容。').pack(pady=8)
    def display(config):
        for variable in variables.values(): variable.set('空位')
        for unit in config['units']:
            variables[unit['row'],unit['column']].set(labels[unit['unit']])
    def save():
        config={'version':1,'units':[
            {'row':row,'column':column,'unit':reverse[variable.get()]}
            for (row,column),variable in variables.items() if variable.get()!='空位']}
        try:
            config=saver(config)
        except (ValueError,KeyError,OSError) as exc:
            messagebox.showerror('无法保存阵型',str(exc),parent=window);return
        if on_saved: on_saved(config)
        window.destroy()
    def clear():
        for variable in variables.values(): variable.set('空位')
    buttons=ttk.Frame(window);buttons.pack(pady=12)
    ttk.Button(buttons,text='恢复默认阵型',command=lambda:display(defaults())).pack(side='left',padx=6)
    ttk.Button(buttons,text='清空',command=clear).pack(side='left',padx=6)
    ttk.Button(buttons,text='保存阵型',command=save).pack(side='left',padx=6)
    ttk.Button(buttons,text='取消',command=window.destroy).pack(side='left',padx=6)
    try:
        display(loader())
    except (ValueError,KeyError,OSError) as exc:
        display(defaults())
        messagebox.showerror('配置读取失败',f'{exc}\n编辑器已显示默认阵型，请重新保存。',parent=window)
    window.wait_visibility();window.focus_set()
    return window
