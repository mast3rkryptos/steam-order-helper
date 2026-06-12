import time
import tkinter as tk

from enum import Enum
from tkinter import *
from tkinter import ttk
from tkinter.ttk import *

class GameSelection(Enum):
    ALL = 1
    STEAM_ONLY = 2
    OTHERS_ONLY = 3

class ProtonCompatibilityMode(Enum):
    NONE = 1
    SOFT = 2
    HARD = 3

if __name__=="__main__":
    root = tk.Tk()
    root.title('Steam Order Helper')
    root.minsize(250, 200)

    gameSelection = tk.StringVar(value=GameSelection.ALL.name)
    forceDataUpdate = tk.BooleanVar()
    protonCompatibility = tk.StringVar(value=ProtonCompatibilityMode.HARD.name)

    comboBox_gameSelection = ttk.Combobox(root, values=[g.name for g in GameSelection], state='readonly')
    comboBox_gameSelection.grid(row=0, sticky=tk.W)
    comboBox_gameSelection.set(GameSelection.ALL.name)

    tk.Checkbutton(root, text='Force Data Update', variable=forceDataUpdate).grid(row=1, sticky=tk.W)

    comboBox_protonCompatibility = ttk.Combobox(root, values=[p.name for p in ProtonCompatibilityMode], state='readonly')
    comboBox_protonCompatibility.grid(row=2, sticky=tk.W)
    comboBox_protonCompatibility.set(ProtonCompatibilityMode.HARD.name)

    progressBar = Progressbar(root, orient=HORIZONTAL, length=200, mode='determinate')

    def bar():
        for value in (20, 40, 50, 60, 80, 100):
            progressBar['value'] = value
            root.update_idletasks()
            time.sleep(1)

    progressBar.grid(row=3)

    Button(root, text='Start', command=bar).grid(row=4)

    root.mainloop()